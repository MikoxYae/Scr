import json
import os

CONFIG_FILE = "data/config.json"


def _load():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {"channel_id": None}


def _save(cfg):
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)


def get_channel():
    return _load().get("channel_id")


def set_channel(channel_id):
    cfg = _load()
    cfg["channel_id"] = channel_id
    _save(cfg)
