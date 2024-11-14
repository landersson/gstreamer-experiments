#!/usr/bin/env python3

import sys
import gi
import time

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib


class DynamicPipeline:
    def __init__(self):
        Gst.init(None)

        # Create pipeline with message-forward enabled
        self.pipeline = Gst.Pipeline.new("dynamic-pipeline")
        self.pipeline.set_property("message-forward", True)

        # Create elements
        self.src = Gst.ElementFactory.make("videotestsrc", "src")
        self.capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
        self.timeoverlay = Gst.ElementFactory.make("timeoverlay", "timeoverlay")
        self.tee = Gst.ElementFactory.make("tee", "tee")
        self.queue_display = Gst.ElementFactory.make("queue", "queue_display")
        self.display_sink = Gst.ElementFactory.make("autovideosink", "display")

        # Configure video resolution
        caps = Gst.Caps.from_string("video/x-raw,width=1024,height=768")
        self.capsfilter.set_property("caps", caps)

        # Add elements to pipeline
        self.pipeline.add(self.src)
        self.pipeline.add(self.capsfilter)
        self.pipeline.add(self.timeoverlay)
        self.pipeline.add(self.tee)
        self.pipeline.add(self.queue_display)
        self.pipeline.add(self.display_sink)

        # Link display branch
        self.src.link(self.capsfilter)
        self.capsfilter.link(self.timeoverlay)
        self.timeoverlay.link(self.tee)
        self.tee.link(self.queue_display)
        self.queue_display.link(self.display_sink)

        # Initialize recording branch elements as None
        self.recording_elements = []
        self.recording_pad = None

        # Add message watch
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message, None)

    def start(self):
        # Start playing
        self.pipeline.set_state(Gst.State.PLAYING)

    def on_message(self, bus, message, data):
        # print("Message received", message.type)
        if message.type == Gst.MessageType.ELEMENT:
            # Check if this is a wrapped EOS message from our filesink
            structure = message.get_structure()
            if (
                structure
                and structure.has_name("GstBinForwarded")
                and structure.has_field("message")
                and structure.get_value("message").type == Gst.MessageType.EOS
            ):
                # structure.get_value("message").src == filesink):

                t = structure.get_value("message").type == Gst.MessageType.EOS
                src = structure.get_value("message").src
                print("EOS message received: type=%s src=%s" % (str(t), str(src)))

                # Now it's safe to remove everything
                # self.pipeline.set_state(Gst.State.PAUSED)

                # # Release the tee pad
                # self.tee.remove_pad(self.recording_pad)
                # self.recording_pad = None

                # # Remove elements from pipeline
                # for element in self.recording_elements:
                #     element.set_state(Gst.State.NULL)
                #     self.pipeline.remove(element)

                # self.recording_elements = []

                # # Resume pipeline playback
                # self.pipeline.set_state(Gst.State.PLAYING)

                # # Remove the message handler
                # bus.remove_signal_watch()
                return False
        return True

    def add_recording_branch(self, filename="test.mp4"):
        # Create recording elements
        queue_record = Gst.ElementFactory.make("queue", "queue_record")
        encoder = Gst.ElementFactory.make("x264enc", "encoder")
        parser = Gst.ElementFactory.make("h264parse", "parser")
        muxer = Gst.ElementFactory.make("mp4mux", "muxer")
        filesink = Gst.ElementFactory.make("filesink", "filesink")

        # Configure elements
        encoder.set_property("tune", "zerolatency")
        filesink.set_property("location", filename)

        # Store elements for later cleanup
        self.recording_elements = [queue_record, encoder, parser, muxer, filesink]

        # Add elements to pipeline
        for element in self.recording_elements:
            self.pipeline.add(element)

        # Link elements
        queue_record.link(encoder)
        encoder.link(parser)
        parser.link(muxer)
        muxer.link(filesink)

        # Get tee src pad
        tee_src_pad_template = self.tee.get_pad_template("src_%u")
        self.recording_pad = self.tee.request_pad(tee_src_pad_template, None, None)
        queue_sink_pad = queue_record.get_static_pad("sink")
        self.recording_pad.link(queue_sink_pad)

        # Set states
        for element in self.recording_elements:
            element.sync_state_with_parent()

    def remove_recording_branch(self):
        if not self.recording_elements:
            return

        filesink = self.recording_elements[-1]  # Get reference to filesink

        # Get the first element's sink pad and unlink first
        queue_record = self.recording_elements[0]
        queue_sink_pad = queue_record.get_static_pad("sink")
        self.recording_pad.unlink(queue_sink_pad)

        # Now send EOS - it can only go downstream
        queue_sink_pad.send_event(Gst.Event.new_eos())

        # Wait a bit for EOS to propagate
        print("Waiting for EOS to propagate...")
        # time.sleep(0.5)
        print("EOS propagated")

        # Unlink and remove elements
        self.pipeline.set_state(Gst.State.PAUSED)

        # Release the tee pad
        self.tee.remove_pad(self.recording_pad)
        self.recording_pad = None

        # Remove elements from pipeline
        for element in self.recording_elements:
            element.set_state(Gst.State.NULL)
            self.pipeline.remove(element)

        self.recording_elements = []

        # Resume pipeline playback
        self.pipeline.set_state(Gst.State.PLAYING)


def main():
    pipeline = DynamicPipeline()
    pipeline.start()

    # Main loop
    loop = GLib.MainLoop()

    def stop_recording():
        print("Removing recording branch...")
        pipeline.remove_recording_branch()
        GLib.timeout_add(2000, loop.quit)
        return False

    def start_recording():
        print("Adding recording branch...")
        pipeline.add_recording_branch("output1.mp4")

        GLib.timeout_add(2000, stop_recording)

        # Record for 2 seconds
        # time.sleep(2)

        # print("Adding recording branch...")
        # pipeline.add_recording_branch("output2.mp4")

        # # Record for 2 seconds
        # time.sleep(2)
        # print("Removing recording branch...")
        # pipeline.remove_recording_branch()

        # Wait a bit more then quit
        # time.sleep(4)
        # loop.quit()
        return False

    # Schedule the test to run after 2 seconds
    GLib.timeout_add(2000, start_recording)

    print("Running main loop")
    try:
        loop.run()
    except KeyboardInterrupt:
        pass

    # Cleanup
    pipeline.pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
