"""Find new / trending products and update the review queue (data/queue.json, data/QUEUE.md)."""
from studio.discover import discover

if __name__ == "__main__":
    discover()
