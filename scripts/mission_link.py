"""Lossy command/telemetry transport, separate from UWB and local FCU links.

Drain disconnected pipes so a worker cannot block on a full telemetry buffer.
Dropped packets are never queued for delivery after reconnection. The recorder
receives only their direction, identity and timestamp, not their payload.
"""


class CommandLink:
    def __init__(self, connections, record):
        self.connections = connections
        self.record = record
        self.resume_at = 0.

    def connected(self, now):
        return now >= self.resume_at

    def receive(self, now):
        for identity, connection in self.connections.items():
            while connection.poll():
                message = connection.recv()
                if not self.connected(now) or message['time'] < self.resume_at:
                    self.record('transport_drop', dict(direction='telemetry', id=identity,
                                time=now, observation_time=message['time']))
                    continue
                self.record('transport_receive', dict(id=identity, time=now,
                            observation_time=message['time']))
                yield identity, message

    def send(self, identity, message, now):
        if not self.connected(now):
            self.record('transport_drop', dict(direction='command', id=identity,
                        time=now, op=message['op']))
            return False
        self.connections[identity].send(message)
        self.record('onboard_command', dict(id=identity, time=now, command=message))
        return True
