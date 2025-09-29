import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship 
from app.database.database import Base


class Movie(Base):
    __tablename__ = "movies"
    id = sa.Column(sa.Integer, primary_key=True)
    title = sa.Column(sa.String, nullable=False)
    duration_minutes = sa.Column(sa.Integer, nullable=False)

class Theater(Base):
    __tablename__ = "theaters"
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String, nullable=False)
    location = sa.Column(sa.String, nullable=True)

class Hall(Base):
    __tablename__ = "halls"
    id = sa.Column(sa.Integer, primary_key=True)
    theater_id = sa.Column(sa.Integer, sa.ForeignKey("theaters.id"), nullable=False)
    name = sa.Column(sa.String, nullable=False)
    # relationships
    seats = relationship("Seat", back_populates="hall", cascade="all, delete-orphan")

class Seat(Base):
    __tablename__ = "seats"
    id = sa.Column(sa.Integer, primary_key=True)
    hall_id = sa.Column(sa.Integer, sa.ForeignKey("halls.id"), nullable=False)
    row_index = sa.Column(sa.Integer, nullable=False)     # 1-based
    seat_number = sa.Column(sa.Integer, nullable=False)   # 1-based in row
    is_aisle = sa.Column(sa.Boolean, default=False)

    hall = relationship("Hall", back_populates="seats")
    __table_args__ = (
        sa.UniqueConstraint("hall_id", "row_index", "seat_number", name="uq_hall_row_seat"),
    )

class Show(Base):
    __tablename__ = "shows"
    id = sa.Column(sa.Integer, primary_key=True)
    movie_id = sa.Column(sa.Integer, sa.ForeignKey("movies.id"), nullable=False)
    hall_id = sa.Column(sa.Integer, sa.ForeignKey("halls.id"), nullable=False)
    start_time = sa.Column(sa.DateTime(timezone=False), nullable=False)
    price = sa.Column(sa.Numeric(8,2), nullable=False)

class ShowSeat(Base):
    __tablename__ = "show_seats"
    id = sa.Column(sa.Integer, primary_key=True)
    show_id = sa.Column(sa.Integer, sa.ForeignKey("shows.id"), nullable=False, index=True)
    row_index = sa.Column(sa.Integer, nullable=False)
    seat_number = sa.Column(sa.Integer, nullable=False)
    status = sa.Column(sa.String, nullable=False, default="available")  # available / booked
    booking_id = sa.Column(sa.Integer, sa.ForeignKey("bookings.id"), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("show_id", "row_index", "seat_number", name="uq_show_row_seat"),
    )

class Booking(Base):
    __tablename__ = "bookings"
    id = sa.Column(sa.Integer, primary_key=True)
    show_id = sa.Column(sa.Integer, sa.ForeignKey("shows.id"), nullable=False)
    group_name = sa.Column(sa.String, nullable=True)
    created_at = sa.Column(sa.DateTime, default=func.now())