from fastapi import FastAPI
import asyncio
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
import dynamic_record


class WebStreamer:
    def __init__(self):
        self.timer_task = None
        self.app = FastAPI(lifespan=self.lifespan)

        # Register routes
        # This line registers a GET endpoint at "/status" that calls the get_status method
        # When a client makes a GET request to "/status", FastAPI will call self.get_status()
        # and return its response as JSON
        self.app.get("/status")(self.get_status)

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        # Startup: create the timer task
        self.timer_task = asyncio.create_task(self.timer_callback())

        yield  # This is where the app runs

        # Shutdown: cancel the timer task
        if self.timer_task:
            self.timer_task.cancel()
            try:
                await self.timer_task
            except asyncio.CancelledError:
                pass

    async def timer_callback(self):
        while True:
            print("HELLO")
            await asyncio.sleep(1)

    async def get_status(self):
        return {
            "status": "operational",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Server is running",
        }

    def run(self, host="0.0.0.0", port=8000):
        uvicorn.run(self.app, host=host, port=port)


if __name__ == "__main__":
    streamer = WebStreamer()
    streamer.run()
