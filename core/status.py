import json
import os

class StatusManager:
    def __init__(self) -> None:
        #path to config file
        base_path = os.path.dirname(os.path.dirname(__file__))
        config_path = os.path.join(base_path, "configs", "status_conf.json")

        try:
            with open(config_path, "r") as f:
                self.config = json.load(f)
        except FileNotFoundError:
            #Fallback is file not found
            self.config = {"theme": {"status_ready": "#ffffff"}}
    
    def get_status_data(self, key):
        #put text and color from config
        theme = self.config.get("theme",{})
        messages = self.config.get("messages", {})

        text = messages.get(key, "Unknown")
        color = theme.get (f"status_{key.lower()}", "#ffffff")

        return text, color


