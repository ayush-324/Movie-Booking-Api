from pydantic import BaseModel, conint
from typing import List, Optional, Tuple
from datetime import datetime


class MovieIn(BaseModel):
    title: str
    duration_minutes: int

class MovieOut(MovieIn):
    id: int

    class Config:
        orm_mode = True

class TheaterIn(BaseModel):
    name: str
    location: Optional[str] = None

class TheaterOut(TheaterIn):
    id: int
    class Config:
        orm_mode = True

class HallCreateRow(BaseModel):
    row_index: conint(ge=1)
    seat_count: conint(ge=6)   
    aisle_seats: Optional[List[int]] = [] 

class HallCreate(BaseModel):
    name: str
    rows: List[HallCreateRow]

class HallOut(BaseModel):
    id: int
    theater_id: int
    name: str
    class Config:
        orm_mode = True

class ShowCreate(BaseModel):
    movie_id: int
    hall_id: int
    start_time: datetime
    price: float

class ShowOut(ShowCreate):
    id: int
    class Config:
        orm_mode = True

class BookingRequest(BaseModel):
    show_id: int
    group_name: Optional[str] = None
    seats_requested: int

class BookingResponse(BaseModel):
    booking_id: int
    seats: List[Tuple[int,int]]  # list of (row_index, seat_number)
