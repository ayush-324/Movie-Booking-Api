from fastapi import FastAPI
from app.database.database import Base, engine


Base.metadata.bind = engine 

app = FastAPI(title="Movie Ticket Booking API")

app.include_router(
    prefix="/user",
    router=__import__("app.routers.user").routers,
    tags=["user"]
)


