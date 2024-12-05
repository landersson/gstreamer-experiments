import asyncio
import gi
import dynamic_record

gi.require_version("Gst", "1.0")
from gi.repository import Gst


class Recorder:
    def __init__(self):
        Gst.init(None)
        self.pipeline = dynamic_record.DynamicPipeline(
            "Testing", dynamic_record.make_test_source()
        )
        self.pipeline.start()

    async def gst_bus_poll_loop(self):
        while True:
            bus = self.pipeline.pipeline.get_bus()
            while bus.have_pending():
                msg = bus.pop()
                self.pipeline.handle_bus_message(bus, msg, None)
                # if msg.type == Gst.MessageType.ERROR:
                #     err, debug = msg.parse_error()
                #     print(f"Error: {err}, Debug: {debug}")
                # elif msg.type == Gst.MessageType.EOS:
                #     print("End of stream")
                # elif msg.type == Gst.MessageType.STATE_CHANGED:
                #     old_state, new_state, pending_state = msg.parse_state_changed()
                #     print(
                #         f"State changed from {old_state.value_nick} to {new_state.value_nick}"
                #     )
                # else:
                #     print(f"Unknown message type: {msg.type}")
                #     # Get next message if available

            await asyncio.sleep(0.1)

    async def stop_recording(self, tee_id):
        print("Removing recording branch...")
        self.pipeline.remove_recording_branch(tee_id)

    async def start_recording(self):
        print("Adding recording branch...")
        tee_id = self.pipeline.add_recording_branch("output1.mp4")

        return tee_id

    async def run(self):

        t = asyncio.create_task(self.gst_bus_poll_loop())

        async def perform_recording():
            await asyncio.sleep(2)
            tee_id = await self.start_recording()
            print(f"Tee ID: {tee_id}")
            await asyncio.sleep(2)
            await self.stop_recording(tee_id)
            await asyncio.sleep(1)
            # await asyncio.get_event_loop().stop()
            t.cancel()

        asyncio.create_task(perform_recording())
        try:
            await t
        except asyncio.CancelledError:
            pass
        self.pipeline.pipeline.set_state(Gst.State.NULL)
        # self.pipeline.stop()


if __name__ == "__main__":
    recorder = Recorder()
    asyncio.run(recorder.run())
    print("DONE")
