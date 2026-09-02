from fastapi import FastAPI

app = FastAPI(title="Nanogrid Central Hub")


@app.get("/")
def home():
    return {
        "message": "Nanogrid Central Hub is running"
    }