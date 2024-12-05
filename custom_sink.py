import gi
import sys

gi.require_version("Gst", "1.0")
gi.require_version("GstBase", "1.0")
from gi.repository import Gst, GstBase
import numpy as np

# Initialize GStreamer
Gst.init(None)


class BailSink(GstBase.BaseSink):
    __gstmetadata__ = (
        "Bail Sink",
        "Sink/Video",
        "Prints the size of incoming video frames",
        "Your Name",
    )

    __gsttemplates__ = (
        Gst.PadTemplate.new(
            "sink",
            Gst.PadDirection.SINK,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string("video/x-raw,format=RGB"),
        ),
    )

    def __init__(self):
        super(BailSink, self).__init__()
        # Set sync to avoid problems with real-time input
        self.set_sync(True)
        self.num_received = 0

    def do_render(self, buffer):
        self.num_received += 1
        if self.num_received > 10:
            sys.stderr.write(">>>>>>>>>>>>>>>>>>>>>>>>>> EOS\n\n\n")
            return Gst.FlowReturn.EOS
        try:
            # Get video frame info
            success, map_info = buffer.map(Gst.MapFlags.READ)
            if not success:
                return Gst.FlowReturn.ERROR

            # Get video frame dimensions from negotiated caps
            caps = self.sinkpad.get_current_caps()
            if not caps:
                return Gst.FlowReturn.ERROR

            structure = caps.get_structure(0)
            width = structure.get_value("width")
            height = structure.get_value("height")

            # Print frame size information
            print(f"Received frame with dimensions: {width}x{height}")
            print(f"Buffer size: {len(map_info.data)} bytes")

            buffer.unmap(map_info)
            return Gst.FlowReturn.OK

        except Exception as e:
            print(f"Error in render: {str(e)}")
            return Gst.FlowReturn.ERROR


def plugin_init(plugin):
    return Gst.Element.register(plugin, "bailsink", Gst.Rank.NONE, BailSink)


def register():
    Gst.Plugin.register_static(
        Gst.VERSION_MAJOR,
        Gst.VERSION_MINOR,
        "bailsink",
        "Bail Sink Plugin",
        plugin_init,
        "1.0",
        "LGPL",
        "bailsink",
        "bailsink",
        "",
    )


# Register the plugin
register()


def main():
    print(Gst.version_string())
    # Create a simple pipeline to test the sink
    # pipeline_str = "videotestsrc num-buffers=5 ! video/x-raw,format=RGB ! bailsink"
    # pipeline_str = "videotestsrc ! video/x-raw,format=RGB ! bailsink"
    pipeline_str = (
        "videotestsrc ! tee name=t t. ! queue ! valve name=valve drop=true ! videoconvert ! video/x-raw,format=RGB ! bailsink "
        "t. ! queue ! autovideosink"
    )
    pipeline = Gst.parse_launch(pipeline_str)

    # Start playing
    pipeline.set_state(Gst.State.PLAYING)

    # Wait until error or EOS
    bus = pipeline.get_bus()
    msg = bus.timed_pop_filtered(
        Gst.CLOCK_TIME_NONE, Gst.MessageType.ERROR | Gst.MessageType.EOS
    )

    # Free resources
    pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
