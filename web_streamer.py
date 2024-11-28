import time
import threading
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import os

class WebStreamer:
    def __init__(self, device='/dev/video4'):
        Gst.init(None)
        
        # Create the pipeline with splitmuxsink
        self.pipeline = Gst.parse_launch(
            f'v4l2src device={device} ! '
            'video/x-raw,width=640,height=480,framerate=30/1 ! videoconvert ! timeoverlay ! '
            'tee name=tekaka '
            'tekaka. ! queue ! videoconvert ! xvimagesink name=display_sink sync=false '
            'tekaka. ! queue name=savequeue ! videoconvert ! valve name=valve drop=false ! '
            'x264enc name=encoder tune=zerolatency ! h264parse ! '
            'splitmuxsink name=splitmux muxer=mp4mux max-size-time=0 max-size-bytes=1000000 async-finalize=true'
        )

        Gst.debug_bin_to_dot_file(self.pipeline, Gst.DebugGraphDetails.ALL, "pipes")
        
        # Get the elements we need to control
        self.valve = self.pipeline.get_by_name('valve')
        self.splitmux = self.pipeline.get_by_name('splitmux')
        self.savequeue = self.pipeline.get_by_name('savequeue')
        self.encoder = self.pipeline.get_by_name('encoder')
        
        # Start the GLib main loop in a separate thread
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run)
        self.thread.daemon = True
        self.thread.start()

        # Start the pipeline
        self.pipeline.set_state(Gst.State.PLAYING)
        
        # Add bus watch
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message::error', self._on_error)
        bus.connect('message::eos', self._on_eos)
    
    def start_recording(self, filename=None):
        """Start recording to a new file"""
        # Generate new filename with timestamp
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        if filename is None:
            new_filename = f"output_{timestamp}.mp4" if filename is None else filename
        else:
            new_filename = filename
        
        # Update the splitmux location
        # self.splitmux.set_property('location', new_filename)
        self.splitmux.set_property('location', "output_%05d.mp4")
        # Enable recording
        self.valve.set_property('drop', False)
        
        print(f"Recording started: {new_filename}")
    
    def stop_recording(self):
        """Stop recording to file"""
        # Stop new data from flowing
        self.valve.set_property('drop', True)
        
        # Request splitmux to finalize the current file
        self.splitmux.emit('split-now')
        time.sleep(0.5)  # Give it a moment to process
        
        print("Recording stopped")
    
    def _on_error(self, bus, msg):
        """Handle error messages"""
        err, debug = msg.parse_error()
        print(f"Error: {err.message}")
        print(f"Debug info: {debug}")
    
    def _on_eos(self, bus, msg):
        """Handle end-of-stream message"""
        print("Received EOS: ", msg)

    def flush(self):
        # Stop the pipeline
        # self.pipeline.send_event(Gst.Event.new_eos())
        self.savequeue.send_event(Gst.Event.new_eos())
        time.sleep(0.5)
        # self.pipeline.set_state(Gst.State.NULL)

    
    def cleanup(self):
        """Clean up resources"""
        # Stop recording if active
        # self.valve.set_property('drop', True)
        
        
        # Quit the GLib main loop
        self.loop.quit()
        self.thread.join()


if __name__ == "__main__":
    os.environ["GST_DEBUG_DUMP_DOT_DIR"] = "/tmp"
    streamer = WebStreamer()
    
    try:
        # Record for 5 seconds
        streamer.start_recording()
        time.sleep(1)
        # for i in range(5):
            # streamer.pipeline.send_event(Gst.Event.new_eos())
        streamer.encoder.send_event(Gst.Event.new_eos())
        time.sleep(2)
        # streamer.pipeline.send_event(Gst.Event.new_eos())
        streamer.pipeline.set_state(Gst.State.NULL)
        # streamer.flush()
        # streamer.stop_recording()
        
        # time.sleep(2)
        
        # # Record for another 5 seconds
        # streamer.start_recording("output_2.mp4")
        # time.sleep(3)
        # streamer.stop_recording()
        
    finally:
        print("Cleaning up")
        streamer.cleanup()
