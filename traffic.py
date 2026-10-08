"""Durable daily totals and rates from WireGuard's per-peer transfer counters."""
from datetime import datetime, timedelta, timezone
import time


class Traffic:
    def init_traffic(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS traffic_daily(day TEXT, peer TEXT, rx INTEGER, tx INTEGER, PRIMARY KEY(day,peer));
        CREATE TABLE IF NOT EXISTS traffic_counters(peer TEXT PRIMARY KEY, boot TEXT, at REAL, rx INTEGER, tx INTEGER, rx_rate REAL, tx_rate REAL);
        ''')
        self.db.commit()

    def record_traffic(self, status, now=None):
        now = time.time() if now is None else now
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        for peer in status.get('peers', []):
            if 'rxBytes' not in peer or 'txBytes' not in peer:
                continue  # Persistent peers absent from the running interface have no counters.
            key = peer['publicKey']
            rx, tx = peer.get('rxBytes', 0), peer.get('txBytes', 0)
            old = self.db.execute('SELECT * FROM traffic_counters WHERE peer=?', (key,)).fetchone()
            drx = dtx = 0
            if old:
                reset = old['boot'] != status.get('bootId', '')
                drx = rx if reset or rx < old['rx'] else rx - old['rx']
                dtx = tx if reset or tx < old['tx'] else tx - old['tx']
            elapsed = max(now - old['at'], 1) if old else 1
            self.db.execute('INSERT INTO traffic_daily VALUES(?,?,?,?) ON CONFLICT(day,peer) DO UPDATE SET rx=rx+excluded.rx,tx=tx+excluded.tx', (day, key, drx, dtx))
            self.db.execute('INSERT OR REPLACE INTO traffic_counters VALUES(?,?,?,?,?,?,?)', (key, status.get('bootId', ''), now, rx, tx, drx / elapsed, dtx / elapsed))
        cutoff = (datetime.fromtimestamp(now, timezone.utc).date() - timedelta(days=35)).isoformat()
        self.db.execute('DELETE FROM traffic_daily WHERE day<?', (cutoff,))
        self.db.commit()

    def traffic_summary(self, days=30):
        now = time.time()
        end = datetime.fromtimestamp(now, timezone.utc).date()
        start = end - timedelta(days=days - 1)
        daily = [dict(r) for r in self.db.execute('SELECT day,SUM(rx) AS rx,SUM(tx) AS tx FROM traffic_daily WHERE day>=? GROUP BY day ORDER BY day', (start.isoformat(),))]
        peers = [dict(r) for r in self.db.execute('SELECT peer,SUM(rx) AS rx,SUM(tx) AS tx FROM traffic_daily WHERE day>=? GROUP BY peer', (start.isoformat(),))]
        rates = {r['peer']: dict(rx=r['rx_rate'], tx=r['tx_rate'], at=r['at']) for r in self.db.execute('SELECT * FROM traffic_counters')}
        for peer in peers:
            rate = rates.get(peer['peer'], {})
            fresh = now - rate.get('at', 0) <= 180
            peer['rxRate'] = rate.get('rx', 0) if fresh else 0
            peer['txRate'] = rate.get('tx', 0) if fresh else 0
            peer['sampleAt'] = rate.get('at')
        return dict(days=days, daily=daily, peers=peers, rx=sum(r['rx'] for r in daily), tx=sum(r['tx'] for r in daily),
                    rxRate=sum(p['rxRate'] for p in peers), txRate=sum(p['txRate'] for p in peers), timezone='UTC',
                    message='Totals start at the first successful sample. Daily buckets use UTC; rates are averages between samples. Offline collection gaps cannot be split accurately across days.')
