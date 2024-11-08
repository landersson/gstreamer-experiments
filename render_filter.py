import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstBase', '1.0')
from gi.repository import Gst, GstBase
import numpy as np

# Initialize GStreamer
Gst.init(None)
# Gst.init_python()

class RedRectangleFilter(GstBase.BaseTransform):
    __gstmetadata__ = (
        'Red Rectangle Filter',
        'Filter/Effect/Video',
        'Draws a red rectangle on video frames',
        'Your Name'
    )

    __gsttemplates__ = (
        Gst.PadTemplate.new(
            'src',
            Gst.PadDirection.SRC,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string('video/x-raw,format=RGB')
        ),
        Gst.PadTemplate.new(
            'sink',
            Gst.PadDirection.SINK,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string('video/x-raw,format=RGB')
        )
    )

    def __init__(self):
        super(RedRectangleFilter, self).__init__()

    def do_transform_ip(self, buf):
        try:
            # Get video frame info
            success, map_info = buf.map(Gst.MapFlags.READ | Gst.MapFlags.WRITE)
            if not success:
                return Gst.FlowReturn.ERROR

            # Get video frame dimensions from negotiated caps
            caps = self.sinkpad.get_current_caps()
            if not caps:
                return Gst.FlowReturn.ERROR
            
            structure = caps.get_structure(0)
            width = structure.get_value('width')
            height = structure.get_value('height')

            # Convert buffer to numpy array
            frame = np.ndarray(
                shape=(height, width, 3),
                dtype=np.uint8,
                buffer=map_info.data
            )

            # Draw red rectangle
            # Rectangle coordinates (x1, y1, x2, y2)
            x1, y1 = width // 4, height // 4
            x2, y2 = (width * 3) // 4, (height * 3) // 4
            
            # Draw horizontal lines
            frame[y1:y1+5, x1:x2, 0] = 255  # Red channel
            frame[y1:y1+5, x1:x2, 1:] = 0   # Green and Blue channels
            frame[y2-5:y2, x1:x2, 0] = 255
            frame[y2-5:y2, x1:x2, 1:] = 0
            
            # Draw vertical lines
            frame[y1:y2, x1:x1+5, 0] = 255
            frame[y1:y2, x1:x1+5, 1:] = 0
            frame[y1:y2, x2-5:x2, 0] = 255
            frame[y1:y2, x2-5:x2, 1:] = 0

            buf.unmap(map_info)
            return Gst.FlowReturn.OK

        except Exception as e:
            print(f"Error in transform: {str(e)}")
            return Gst.FlowReturn.ERROR

def plugin_init(plugin):
    return Gst.Element.register(plugin, "redrectangle", Gst.Rank.NONE, RedRectangleFilter)

def register():
    Gst.Plugin.register_static(
        Gst.VERSION_MAJOR,
        Gst.VERSION_MINOR,
        "redrectangle",
        "Red Rectangle Filter",
        plugin_init,
        "1.0",
        "LGPL",
        "redrectangle",
        "redrectangle",
        ""
    )

# Register the plugin
register()

def main():
    print(Gst.version_string())
    # Create pipeline
    # pipeline_str = "videotestsrc ! video/x-raw,format=RGB ! redrectangle ! videoconvert ! autovideosink"
    # pipeline_str = "videotestsrc ! video/x-raw,format=RGB ! redrectangle ! videoconvert ! autofilesink location=output.png"
    pipeline_str = "videotestsrc num-buffers=1 ! video/x-raw,format=RGB ! redrectangle ! videoconvert ! pngenc ! filesink location=output.png"
    pipeline = Gst.parse_launch(pipeline_str)

    # Start playing
    pipeline.set_state(Gst.State.PLAYING)

    # Wait until error or EOS
    bus = pipeline.get_bus()
    msg = bus.timed_pop_filtered(
        Gst.CLOCK_TIME_NONE,
        Gst.MessageType.ERROR | Gst.MessageType.EOS
    )

    # Free resources
    pipeline.set_state(Gst.State.NULL)

if __name__ == '__main__':
    main()
