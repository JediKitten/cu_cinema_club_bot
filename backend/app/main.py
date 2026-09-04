from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, film_requests, films, interests
from app.services.tmdb import get_tmdb


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await get_tmdb().aclose()


app = FastAPI(
    title="Университетский киноклуб",
    version="0.1.0",
    lifespan=lifespan,
    description=(
        "Данные о фильмах предоставлены TMDB. "
        "This product uses the TMDB API but is not endorsed or certified by TMDB."
    ),
)

# Mini App грузится с домена фронта, а не с домена API.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(films.router)
app.include_router(interests.router)
app.include_router(film_requests.router)
app.include_router(admin.router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
