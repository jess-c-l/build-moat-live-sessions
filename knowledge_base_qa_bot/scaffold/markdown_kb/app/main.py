from dotenv import load_dotenv
from fastapi import FastAPI

from .indexer import load_index_json
from .routes import router

load_dotenv()

app = FastAPI(title="Markdown Knowledge Base Q&A Bot")
app.include_router(router)


@app.on_event("startup")
def load_persisted_index():
    load_index_json()
