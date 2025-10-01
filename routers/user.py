from fastapi import APIRouter, Depends, HTTPException
import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, update
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from app.database.database import get_db
from app.model.model import Movie, Theater, Hall, Seat, Show, ShowSeat, Booking
from app.schemas.schemas import (
    MovieIn, MovieOut,  TheaterIn, TheaterOut,
    HallCreate, HallCreateRow, HallOut,
    ShowCreate, ShowOut,
    BookingRequest, BookingResponse
)

router = APIRouter()



@router.post("/movies", response_model=MovieOut)
async def create_movie(payload: MovieIn, db: AsyncSession = Depends(get_db)):
    m = Movie(title=payload.title, duration_minutes=payload.duration_minutes)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m

@router.get("/movies", response_model=List[MovieOut])
async def list_movies(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Movie))
    return res.scalars().all()

@router.get("/movies/{movie_id}", response_model=MovieOut)
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.get(Movie, movie_id)
    if not r:
        raise HTTPException(404, "movie not found")
    return r

# ---------- Theaters & Halls ----------
@router.post("/theaters", response_model=TheaterOut)
async def create_theater(payload: TheaterIn, db: AsyncSession = Depends(get_db)):
    t = Theater(name=payload.name, location=payload.location)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t

@router.post("/theaters/{theater_id}/halls", response_model=HallOut)
async def create_hall(theater_id: int, payload: HallCreate, db: AsyncSession = Depends(get_db)):
    # validate theater exists
    t = await db.get(Theater, theater_id)
    if not t:
        raise HTTPException(404, "theater not found")
    h = Hall(theater_id=theater_id, name=payload.name)
    db.add(h)
    await db.flush()  # get h.id
    # create seat layout
    for r in payload.rows:
        if r.seat_count < 6:
            raise HTTPException(400, "each row must have at least 6 seats")
        for seat_num in range(1, r.seat_count + 1):
            is_aisle = seat_num in (r.aisle_seats or [])
            seat = Seat(hall_id=h.id, row_index=r.row_index, seat_number=seat_num, is_aisle=is_aisle)
            db.add(seat)
    await db.commit()
    await db.refresh(h)
    return h

@router.get("/theaters/{theater_id}/halls/{hall_id}/layout")
async def hall_layout(theater_id: int, hall_id: int, db: AsyncSession = Depends(get_db)):
    # returns seat layout (rows -> seats)
    q = select(Seat).where(Seat.hall_id == hall_id).order_by(Seat.row_index, Seat.seat_number)
    res = await db.execute(q)
    seats = res.scalars().all()
    if not seats:
        raise HTTPException(404, "no seats / hall not found")
    layout = {}
    for s in seats:
        layout.setdefault(s.row_index, []).append({"seat_number": s.seat_number, "is_aisle": s.is_aisle})
    return {"hall_id": hall_id, "layout": layout}

# ---------- Shows ----------
@router.post("/shows", response_model=ShowOut)
async def create_show(payload: ShowCreate, db: AsyncSession = Depends(get_db)):
    # validate movie and hall exist
    movie = await db.get(Movie, payload.movie_id)
    hall = await db.get(Hall, payload.hall_id)
    if not movie or not hall:
        raise HTTPException(404, "movie or hall not found")
    show = Show(movie_id=payload.movie_id, hall_id=payload.hall_id, start_time=payload.start_time, price=payload.price)
    db.add(show)
    await db.flush()
    # create show seats by copying hall seats
    q = select(Seat).where(Seat.hall_id == payload.hall_id)
    res = await db.execute(q)
    hall_seats = res.scalars().all()
    for hs in hall_seats:
        ss = ShowSeat(show_id=show.id, row_index=hs.row_index, seat_number=hs.seat_number, status="available")
        db.add(ss)
    await db.commit()
    await db.refresh(show)
    return show

@router.get("/shows/{show_id}")
async def get_show(show_id: int, db: AsyncSession = Depends(get_db)):
    s = await db.get(Show, show_id)
    if not s:
        raise HTTPException(404, "show not found")
    return s

@router.get("/shows/{show_id}/seats")
async def show_seats(show_id: int, db: AsyncSession = Depends(get_db)):
    q = select(ShowSeat).where(ShowSeat.show_id == show_id).order_by(ShowSeat.row_index, ShowSeat.seat_number)
    res = await db.execute(q)
    seats = res.scalars().all()
    if not seats:
        raise HTTPException(404, "show seats not found")
    layout = {}
    for s in seats:
        layout.setdefault(s.row_index, []).append({"seat_number": s.seat_number, "status": s.status})
    return {"show_id": show_id, "layout": layout}

# ---------- Booking logic ----------
async def find_contiguous_in_show(db: AsyncSession, show_id: int, group_size: int) -> Optional[List[Tuple[int,int]]]:
    """
    Search for contiguous run of seats (group_size) in any row for the given show that are available.
    Returns list of (row_index, seat_number) or None.
    """
    # fetch seats ordered by row and seat number
    q = select(ShowSeat).where(ShowSeat.show_id == show_id).order_by(ShowSeat.row_index, ShowSeat.seat_number)
    res = await db.execute(q)
    all_seats = res.scalars().all()
    if not all_seats:
        return None
    # group by row
    from collections import defaultdict
    rows = defaultdict(list)
    for s in all_seats:
        if s.status == "available":
            rows[s.row_index].append(s.seat_number)
    # look for contiguous run
    for row_idx, seat_list in rows.items():
        seat_list.sort()
        # sliding window to find consecutive numbers of length group_size
        for i in range(len(seat_list) - group_size + 1):
            window = seat_list[i:i+group_size]
            # check strictly consecutive
            if all(window[j] + 1 == window[j+1] for j in range(len(window)-1)):
                return [(row_idx, sn) for sn in window]
    return None

async def suggest_other_shows(db: AsyncSession, target_show: Show, group_size: int, time_window_minutes: int = 180):
    """
    Suggest other shows of same movie within time window or other movies that can seat group together
    """
    start = target_show.start_time - timedelta(minutes=time_window_minutes)
    end = target_show.start_time + timedelta(minutes=time_window_minutes)
    q = select(Show).where(Show.start_time.between(start, end)).order_by(Show.start_time)
    res = await db.execute(q)
    candidates = res.scalars().all()
    suggestions = []
    for s in candidates:
        contiguous = await find_contiguous_in_show(db, s.id, group_size)
        if contiguous:
            suggestions.append({"show_id": s.id, "start_time": s.start_time.isoformat(), "seats": contiguous})
    return suggestions

@router.post("/book", response_model=BookingResponse)
async def book_group(payload: BookingRequest, db: AsyncSession = Depends(get_db)):
    """
    Attempt to make a group booking for the given show_id and seats_requested (must be together).
    Concurrency-safe via transaction and row locking.
    """
    # Validate show exists
    show = await db.get(Show, payload.show_id)
    if not show:
        raise HTTPException(404, "show not found")

    # first try to find contiguous seat
    contiguous = await find_contiguous_in_show(db, payload.show_id, payload.seats_requested)
    if contiguous is None:
        # return suggestions
        suggestions = await suggest_other_shows(db, show, payload.seats_requested)
        raise HTTPException(
            status_code=409,
            detail={"message": "cannot find contiguous seats in requested show", "suggestions": suggestions}
        )

  
    async with db.begin():
        # Lock all show_seats for the rows we need within the transaction
        rows_to_lock = sorted(set(r for r, _ in contiguous))
        # lock seats in those rows (FOR UPDATE)
        q_lock = select(ShowSeat).where(and_(ShowSeat.show_id == payload.show_id, ShowSeat.row_index.in_(rows_to_lock))).with_for_update()
        await db.execute(q_lock)

        # re-check availability for requested contiguous seats
        q_check = select(ShowSeat).where(
            and_(
                ShowSeat.show_id == payload.show_id,
                sa.tuple_(ShowSeat.row_index, ShowSeat.seat_number).in_(contiguous)
            )
        )
        res = await db.execute(q_check)
        seats_now = res.scalars().all()
        if any(s.status != "available" for s in seats_now) or len(seats_now) != len(contiguous):
            # someone took seats concurrently
            raise HTTPException(409, "some seats became unavailable while booking; please retry or choose alternatives")
        # create booking
        booking = Booking(show_id=payload.show_id, group_name=payload.group_name)
        db.add(booking)
        await db.flush()
        # mark seats booked
        q_upd = update(ShowSeat).where(
            and_(
                ShowSeat.show_id == payload.show_id,
                sa.tuple_(ShowSeat.row_index, ShowSeat.seat_number).in_(contiguous)
            )
        ).values(status="booked", booking_id=booking.id)
        await db.execute(q_upd)
    
    return BookingResponse(booking_id=booking.id, seats=contiguous)


@router.get("/bookings/{booking_id}")
async def get_booking(booking_id: int, db: AsyncSession = Depends(get_db)):
    b = await db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "booking not found")
    q = select(ShowSeat).where(ShowSeat.booking_id == booking_id)
    res = await db.execute(q)
    seats = res.scalars().all()
    seats_list = [(s.row_index, s.seat_number) for s in seats]
    return {"booking": {"id": b.id, "show_id": b.show_id, "group_name": b.group_name, "created_at": b.created_at}, "seats": seats_list}

@router.get("/shows/{show_id}/availability_summary")
async def availability_summary(show_id:int, db: AsyncSession=Depends(get_db)):
    q = select(ShowSeat.row_index, func.count().label("total"), func.sum(func.case([(ShowSeat.status=='available',1)], else_=0)).label("available")).where(ShowSeat.show_id==show_id).group_by(ShowSeat.row_index)
    res = await db.execute(q)
    rows = [{"row_index": r[0], "total": r[1], "available": r[2]} for r in res.all()]
    return {"show_id": show_id, "rows": rows}
