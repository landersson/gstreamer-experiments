#!/usr/bin/env python3
import gi
import sys
import time
import logging
import threading

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

# Configure logging
logging.basicConfig(
    # level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    level=logging.INFO,
    format=" %(relativeCreated)04d - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def save_dot_file(pipeline, name):
    pass
    # Gst.debug_bin_to_dot_file(pipeline, Gst.DebugGraphDetails.ALL, name)


def print_structure(structure):
    logger.info("Structure: %s", structure)
    n_fields = structure.n_fields()
    logger.info("name=%s", structure.get_name())
    logger.info("n_fields=%d", n_fields)
    for i in range(n_fields):
        field_name = structure.nth_field_name(i)
        logger.info("  %s=%s", field_name, structure.get_value(field_name))

    if structure.has_field("message"):
        message = structure.get_value("message")
        logger.info("message.src: %s", message.src)
        logger.info("message.type: %s", message.type)


class Branch:
    def __init__(self, name):
        self.name = name
        self.dynpipe = None
        self.elements = []

    def add_to_pipeline(self, dynamic_pipeline):
        self.dynpipe = dynamic_pipeline
        self.add_and_link_elements()
        # for element in self.elements:
            # element.set_state(Gst.State.PLAYING)
        self.tee_pad = self.dynpipe.add_branch_to_tee(self)
        self.sync_elements()
        save_dot_file(self.dynpipe.pipeline, "branch_added_%s" % self.name)

    def add_and_link_elements(self):
        """Add elements to pipeline and link them up"""
        for element in self.elements:
            self.dynpipe.add(element)

        for i in range(len(self.elements) - 1):
            self.elements[i].link(self.elements[i + 1])

    def sync_elements(self):
        for element in self.elements:
            element.sync_state_with_parent()

    def queue(self):
        return self.elements[0]

    def queue_sink_pad(self):
        return self.queue().get_static_pad("sink")

    def initiate_removal(self):
        self.tee_pad.add_probe(
            Gst.PadProbeType.IDLE, self._default_remove_branch_probe_cb, None
        )

    def _default_remove_branch_probe_cb(self, tee_pad, info, _data):
        tee_pad.remove_probe(info.id)
        self._remove_branch_from_tee()
        self.dynpipe.remove_branch_elements(self)
        return Gst.PadProbeReturn.REMOVE

    def _remove_branch_from_tee(self):
        # NOTE: This method should only be called when pad is idle/blocked

        self.tee_pad.unlink(self.queue_sink_pad())
        # ???: Is it ok to remove pad from tee in a probe callback for the same pad?
        self.dynpipe.tee.remove_pad(self.tee_pad)


class RecordingBranch(Branch):
    """
    A branch that records video to a file.
    """

    def __init__(self, filename):
        super().__init__("recording")

        self.filename = filename
        logger.info("New recording branch writing to %s", filename)

        # Create recording elements
        recording_queue = Gst.ElementFactory.make("queue", "rb_queue")
        converter = Gst.ElementFactory.make("videoconvert", "rb_converter")
        encoder = Gst.ElementFactory.make("x264enc", "rb_encoder")
        parser = Gst.ElementFactory.make("h264parse", "rb_parser")
        muxer = Gst.ElementFactory.make("mp4mux", "rb_muxer")
        filesink = Gst.ElementFactory.make("filesink", "rb_filesink")

        # Configure elements
        encoder.set_property("tune", "zerolatency")
        filesink.set_property("location", filename)

        self.elements = [recording_queue, converter, encoder, parser, muxer, filesink]

    def sink(self):
        return self.elements[-1]

    def _rec_pad_probe_cb(self, tee_pad, info, _data):

        # ???: Apparently, pad probes can be called multiple times.
        # From: https://coaxion.net/blog/2014/01/gstreamer-dynamic-pipelines/
        #  "Also it is important to keep in mind that the callback can be called
        #   multiple times (also at once), and that it can also still be called
        #   when returning GST_PAD_PROBE_REMOVE from it (another thread might’ve
        #   just called into it). It is the job of the callback to protect
        #   against that.""
        #
        # ???: Is removing the probe here enough to ensure that we only run the code below once?
        tee_pad.remove_probe(info.id)

        self._remove_branch_from_tee()

        # For an mp4 recording branch, we need to send an EOS event downstream in order to
        # make the encoder/muxer/filesink elements flush their buffers and finish writing
        # the video output file properly.

        # Send EOS event on branch queue sink pad - it can only go downstream

        # ???: Is it ok to send EOS event from a probe callback? In this example, a new thread is
        # created to send the EOS event:
        # https://gitlab.freedesktop.org/freedesktop/snippets/-/snippets/1760#L81
        self.queue_sink_pad().send_event(Gst.Event.new_eos())

        # Add ourselves to the list of branches waiting for an EOS message. This is done so that we
        # can postpone the removal of branch elements until after the EOS message has been received,
        # in order to make sure that the encoder/muxer/filesink elements have finished writing the
        # output file properly. When the sink element has finised up writing the file, it will send an
        # EOS message upstream. This EOS message will caught by the custom bus message handler,
        # which will then unlink and remove the branch.
        logger.info("RecordingBranch: Waiting for EOS to propagate...")
        self.dynpipe.branches_waiting_for_eos_message[self.sink()] = self
        return Gst.PadProbeReturn.REMOVE

    def initiate_removal(self):
        self.tee_pad.add_probe(Gst.PadProbeType.IDLE, self._rec_pad_probe_cb, self)


class DisplayBranch(Branch):
    """
    A branch that displays video on the screen.
    """

    def __init__(self):
        super().__init__("display")
        logger.info("New display branch...")
        display_queue = Gst.ElementFactory.make("queue", "display_queue")
        # NOTE: autovideosink seems to hang indefinitely when being removed from pipeline
        # display_sink = Gst.ElementFactory.make("autovideosink", "display")
        converter = Gst.ElementFactory.make("videoconvert", "db_converter")
        display_sink = Gst.ElementFactory.make("xvimagesink", "db_display")

        self.elements = [display_queue, converter, display_sink]
        # self.elements = [display_queue, display_sink]


class DynamicPipeline:
    """
    A gstreamer pipeline that supports dynamic addition and removal of various branches.
    """

    error_dot_saved = False

    def __init__(self, name, source_elements=[]):

        self.pipeline = Gst.Pipeline.new(name)

        # The property "message-forward" needs to be True in order to receive
        # EOS messages on the pipeline bus from individual elements. Used by
        # RecordingBranch, which needs to wait for the EOS message from the
        # filesink in order to delay the removal of the branch elements.
        self.pipeline.set_property("message-forward", True)

        # Create elements
        self.tee = Gst.ElementFactory.make("tee", "tee")
        self.pipeline.add(self.tee)

        for element in source_elements:
            self.pipeline.add(element)

        for i in range(len(source_elements) - 1):
            source_elements[i].link(source_elements[i + 1])
        source_elements[-1].link(self.tee)

        self.add_fake_sink()

        self.next_tee_id = 0
        self.tee_branches = {}
        self.branches_waiting_for_eos_message = {}

    def add_fake_sink(self):
        # We need to create a dummy branch+queue+sink in order for the pipeline to start
        self.fake_queue = Gst.ElementFactory.make("queue", "fake_queue")
        self.fake_sink = Gst.ElementFactory.make("fakesink", "fake_sink")

        self.pipeline.add(self.fake_queue)
        self.pipeline.add(self.fake_sink)

        self.tee.link(self.fake_queue)
        self.fake_queue.link(self.fake_sink)

    def add_glib_bus_watch(self):
        # This needs a running glib mainloop to work
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.handle_bus_message, None)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)

    def add(self, element):
        self.pipeline.add(element)

    # def link_tee_pad_cb(self, tee_pad, info, branch):
    #     # self.pipeline.set_state(Gst.State.PAUSED)
    #     tee_pad.link(branch.queue_sink_pad())
    #     branch.queue().sync_state_with_parent()
    #     # self.pipeline.set_state(Gst.State.PLAYING)
    #     return Gst.PadProbeReturn.REMOVE

    def add_branch_to_tee(self, branch, tee_src_pad_name="src_%u"):

        # Add new tee pad to tee element
        tee_src_pad_template = self.tee.get_pad_template(tee_src_pad_name)
        tee_pad = self.tee.request_pad(tee_src_pad_template, None, None)

        # ???: In certain cases, we need to set the pipeline to paused before
        # linking a branch to the tee and then set it back to playing. For
        # example, this is needed when adding a recording branch after having
        # added _and_ removed a display branch. Why?

        # self.pipeline.set_state(Gst.State.PAUSED)
        tee_pad.link(branch.queue_sink_pad())
        # self.pipeline.set_state(Gst.State.PLAYING)
        # ???: In general, do we need to use a blocking probe to add a branch to
        # a tee? Assuming no above.

        # tee_pad.add_probe(Gst.PadProbeType.IDLE, self.link_tee_pad_cb, branch)
        return tee_pad

    def object_name_short(self, object_name):
        return str(object_name).split("(")[1].split(")")[0]

    def state_name_short(self, state_name):
        return str(state_name).split()[1].split("_")[-1]

    def handle_bus_message(self, bus, message, _data):
        # logger.info("------------- Message received %s", message.type)
        if message.type == Gst.MessageType.ELEMENT:
            # Check if this is a wrapped EOS message from our filesink
            structure = message.get_structure()
            if (
                structure
                and structure.has_name("GstBinForwarded")
                and structure.has_field("message")
                and structure.get_value("message").type == Gst.MessageType.EOS
            ):

                src = structure.get_value("message").src
                logger.info("EOS message received: src=%s", src)

                if src in self.branches_waiting_for_eos_message:
                    branch = self.branches_waiting_for_eos_message[src]
                    del self.branches_waiting_for_eos_message[src]

                    self.remove_branch_elements(branch)

                return False
            else:
                logger.debug("Unhandled ELEMENT message received: src=%s", message.src)
                # print_structure(message.get_structure())
                return False

        elif message.type == Gst.MessageType.ERROR:
            logger.error("Error message received: %s", message.parse_error())
            if not self.error_dot_saved:
                logger.error("Saving error dot file")
                save_dot_file(self.pipeline, "error")
                self.error_dot_saved = True

        elif message.type == Gst.MessageType.WARNING:
            logger.warning("Warning message received: %s", message.parse_warning())

        elif message.type == Gst.MessageType.STATE_CHANGED:
            structure = message.get_structure()
            old_state, new_state, pending_state = message.parse_state_changed()
            logger.debug(
                "State changed: src=%s, %s->%s",
                self.object_name_short(str(message.src)),
                self.state_name_short(old_state),
                self.state_name_short(new_state),
            )
        elif message.type == Gst.MessageType.STREAM_STATUS:
            pass
            # logger.info("Stream status changed: %s", message.parse_stream_status())
        else:
            pass
            # logger.debug("Unhandled message type: %s", message.type)
        return True

    def add_branch(self, branch):
        """Register a new branch and return a numeric identifier for future reference"""
        self.tee_branches[self.next_tee_id] = branch
        branch.tee_id = self.next_tee_id
        self.next_tee_id += 1
        branch.add_to_pipeline(self)
        return branch.tee_id

    def remove_branch_elements(self, branch):
        # Remove elements from pipeline
        for element in branch.elements:
            element.set_state(Gst.State.NULL)
            self.pipeline.remove(element)

        del self.tee_branches[branch.tee_id]

    def remove_branch(self, tee_id):
        logger.info("Removing branch %s", tee_id)
        branch = self.tee_branches[tee_id]
        branch.initiate_removal()


def make_test_source(width=1024, height=768):
    src = Gst.ElementFactory.make("videotestsrc", "src")
    capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
    timeoverlay = Gst.ElementFactory.make("timeoverlay", "timeoverlay")

    src.set_property("is-live", True)

    # caps = Gst.Caps.from_string(f"video/x-raw,width={width},height={height},profile=high-4:2:2")
    # caps = Gst.Caps.from_string(f"video/x-raw,width={width},height={height},format=YV12")
    # caps = Gst.Caps.from_string(f"video/x-raw,width={width},height={height},format=RGB")
    caps = Gst.Caps.from_string(f"video/x-raw,width={width},height={height},format=Y444")
    # caps = Gst.Caps.from_string(f"video/x-raw,width={width},height={height}")
    capsfilter.set_property("caps", caps)

    return src, capsfilter, timeoverlay


def make_v4l2_source(device="/dev/video0", width=1280, height=720):
    """
    Make a v4l2 source pipeline reading and decoding jpeg images.
    """
    src = Gst.ElementFactory.make("v4l2src", "src")
    src.set_property("device", device)

    capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
    decoder = Gst.ElementFactory.make("avdec_mjpeg", "decoder")
    videoconvert = Gst.ElementFactory.make("videoconvert", "videoconvert")
    timeoverlay = Gst.ElementFactory.make("timeoverlay", "timeoverlay")

    caps = Gst.Caps.from_string(f"image/jpeg,width={width},height={height}")
    capsfilter.set_property("caps", caps)

    return src, capsfilter, decoder, videoconvert, timeoverlay


def scenario_1(loop, pipeline):
    """
    Scenario 1: Start/stop recording video twice with no other branches running
    """

    def start_recording(filename):
        tee_id = pipeline.add_branch(RecordingBranch(filename))
        # Schedule removal of recording branch after 1 second
        GLib.timeout_add(1000, lambda: pipeline.remove_branch(tee_id))
        return False

    GLib.timeout_add(1000, start_recording, "output1.mp4")
    GLib.timeout_add(3000, start_recording, "output2.mp4")
    GLib.timeout_add(5000, loop.quit)


def scenario_2(loop, pipeline):
    """
    Scenario 2: Start display branch after 1 sec, then remove it after 500ms.
                Record video between 2 and 3 secs.
                NOTE: This scenario fails unless we pause the pipeline before adding
                the recording branch to the tee source pad.
    """

    def start_recording(filename):
        tee_id = pipeline.add_branch(RecordingBranch(filename))
        GLib.timeout_add(1000, lambda: pipeline.remove_branch(tee_id))
        return False

    def add_display_branch():
        tee_id = pipeline.add_branch(DisplayBranch())
        # XXX: If we uncomment this to remove the display branch before adding the recording branch,
        #      caps renegotiation fails and the pipeline stops processing data.
        GLib.timeout_add(500, lambda: pipeline.remove_branch(tee_id))

        # If we remove the display branch after adding the recording branch, it works fine.
        # GLib.timeout_add(1500, lambda: pipeline.remove_display_branch(tee_id))
        return False

    GLib.timeout_add(1000, add_display_branch)
    # GLib.timeout_add(2000, add_display_branch)
    GLib.timeout_add(2000, start_recording, "output1.mp4")
    GLib.timeout_add(1200, lambda: save_dot_file(pipeline.pipeline, "disp_added"))
    GLib.timeout_add(1800, lambda: save_dot_file(pipeline.pipeline, "disp_removed"))
    GLib.timeout_add(2200, lambda: save_dot_file(pipeline.pipeline, "recording"))
    GLib.timeout_add(5000, loop.quit)


def main():
    Gst.init(None)

    pipeline = DynamicPipeline("DynamicPipeline", make_test_source())
    # pipeline = DynamicPipeline(
    #     "DynamicPipeline", make_v4l2_source("/dev/video4", 1280, 720)
    # )
    pipeline.add_glib_bus_watch()
    pipeline.start()

    loop = GLib.MainLoop()

    # Scenario 1: Start/stop recording video only, works fine
    # scenario_1(loop, pipeline)

    # Scenario 2: Add a display branch and a recording branch simultaneously
    scenario_2(loop, pipeline)

    logger.info("Running main loop")
    try:
        loop.run()
    except KeyboardInterrupt:
        pass

    pipeline.stop()
    Gst.deinit()
    logger.info("Done")


if __name__ == "__main__":
    main()
