'''
ROS 2 parts for Donkey Car.

Requires a ROS 2 install with Python bindings, e.g.:
  sudo apt install ros-humble-rclpy ros-humble-std-msgs

Source your ROS 2 workspace before running the vehicle, e.g.:
  source /opt/ros/humble/setup.bash
'''
import os
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, Int32, String


def _ensure_rclpy():
    if not rclpy.ok():
        rclpy.init()


def _node_name(name, anonymous):
    if anonymous:
        return f'{name}_{os.getpid()}'
    return name


def _to_msg(stream_type, data):
    '''Wrap a Python value in a std_msgs message instance.'''
    if isinstance(data, stream_type):
        return data
    msg = stream_type()
    msg.data = data
    return msg


class Ros2Publisher(object):
    '''
    Publish Donkey Car pipeline values to a ROS 2 topic.
    '''

    def __init__(self, node_name, channel_name, stream_type=String,
                 anonymous=True, qos_depth=10):
        _ensure_rclpy()
        self.stream_type = stream_type
        self.data = None
        self.node = Node(_node_name(node_name, anonymous))
        self.pub = self.node.create_publisher(stream_type, channel_name, qos_depth)

    def run(self, data):
        '''Only publish when the data stream changes.'''
        if data != self.data and rclpy.ok():
            self.data = data
            self.pub.publish(_to_msg(self.stream_type, data))

    def shutdown(self):
        self.node.destroy_node()


class Ros2Subscriber(object):
    '''
    Subscribe to a ROS 2 topic and expose the latest value to the Donkey pipeline.
    '''

    def __init__(self, node_name, channel_name, stream_type=String,
                 anonymous=True, qos_depth=10):
        _ensure_rclpy()
        self.data = None
        self._lock = threading.Lock()
        self.node = Node(_node_name(node_name, anonymous))
        self.node.create_subscription(
            stream_type, channel_name, self._on_data_recv, qos_depth)

    def _on_data_recv(self, msg):
        with self._lock:
            self.data = msg.data

    def run(self):
        if rclpy.ok():
            rclpy.spin_once(self.node, timeout_sec=0)
        with self._lock:
            return self.data

    def shutdown(self):
        self.node.destroy_node()
