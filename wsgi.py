import uvicorn
from app import app, seed_database

if __name__ == "__main__":
    seed_database()
    uvicorn.run(app, host="0.0.0.0", port=5000)
