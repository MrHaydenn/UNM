"""Bounded per-client UDP proxy with idle session cleanup."""
import asyncio
import time


class Reply(asyncio.DatagramProtocol):
    def __init__(self, parent, client):
        self.parent, self.client = parent, client

    def datagram_received(self, data, address):
        session = self.parent.sessions.get(self.client)
        if session:
            session['at'] = time.monotonic()
            self.parent.transport.sendto(data, self.client)


class UDPProxy(asyncio.DatagramProtocol):
    def __init__(self, target, limit=256):
        self.target, self.limit = target, limit
        self.sessions, self.pending, self.queued = {}, {}, {}
        self.transport, self.cleanup = None, None

    def connection_made(self, transport):
        self.transport = transport
        self.cleanup = asyncio.create_task(self.expire())

    def datagram_received(self, data, client):
        session = self.sessions.get(client)
        if session:
            session['at'] = time.monotonic()
            session['transport'].sendto(data)
        elif client in self.pending:
            if len(self.queued[client]) < 32:
                self.queued[client].append(data)
        elif len(self.sessions) + len(self.pending) < self.limit:
            self.queued[client] = []
            self.pending[client] = asyncio.create_task(self.open(client, data))

    async def open(self, client, data):
        try:
            target = self.target
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: Reply(self, client), remote_addr=target)
            self.sessions[client] = dict(transport=transport, at=time.monotonic())
            transport.sendto(data)
            for packet in self.queued.get(client, []):
                transport.sendto(packet)
        except OSError:
            pass
        finally:
            self.pending.pop(client, None)
            self.queued.pop(client, None)

    async def expire(self):
        while True:
            await asyncio.sleep(15)
            for client, session in list(self.sessions.items()):
                if time.monotonic() - session['at'] > 60:
                    session['transport'].close()
                    self.sessions.pop(client, None)

    def close(self):
        if self.cleanup:
            self.cleanup.cancel()
        for task in self.pending.values():
            task.cancel()
        for session in self.sessions.values():
            session['transport'].close()
        self.sessions.clear()
        if self.transport:
            self.transport.close()

    def update_target(self, target):
        if target != self.target:
            for session in self.sessions.values():
                session['transport'].close()
            self.sessions.clear()
            for task in self.pending.values():
                task.cancel()
            self.target = target
