from fastapi import FastAPI

from app.api.router import api_router

app = FastAPI(title="Portfolio Rebalancer", version="1.0.0")
app.include_router(api_router)
