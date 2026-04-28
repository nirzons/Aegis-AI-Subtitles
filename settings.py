import os
import json


class SettingsManager:
    def __init__(self, filename="translator_settings.json"):
        self.filename = os.path.join(os.getcwd(), filename)
        self.config = {
            "api_keys": {},
            "models": {}
        }
        self.load_settings()

    def get_active_profile(self):
        from language_profiles import get_profile
        trans_cfg = self.config.get("translation", {})
        source_code = trans_cfg.get("source_lang_code", "en")
        target_code = trans_cfg.get("target_lang_code", "he")
        
        profile = get_profile(source_code, target_code)
        
        if trans_cfg.get("use_native_instructions"):
            profile.use_native_instructions = True
            
        max_words = trans_cfg.get("max_words_per_line_override")
        if max_words is not None:
            profile.max_words_per_line = int(max_words)
            
        return profile

    def load_defaults(self):
        return {
            "translation": {
                "source_lang_code": "en",
                "target_lang_code": "he",
                "use_native_instructions": False,
                "max_words_per_line_override": None
            },
            "api_keys": {
                "google": os.environ.get("GEMINI_API_KEY") or "",
                "openai": os.environ.get("OPENAI_API_KEY") or "",
                "deepseek": os.environ.get("DEEPSEEK_API_KEY") or "",
                "lmstudio": "lm-studio-dummy-key"
            },
            "models": {
                "1": { "name": "gemini-2.5-flash", "provider": "google", "batch_size": 30, "temperature": 0.5, "input_price": 1.50, "output_price": 6.25, "cache_discount": 0.0 },
                "2": { "name": "gemini-2.5-flash-lite", "provider": "google", "batch_size": 15, "temperature": 0.0, "input_price": 0.1, "output_price": 0.4, "cache_discount": 0.0 },
                "3": { "name": "gpt-4o", "provider": "openai", "batch_size": 25, "temperature": 0.02, "input_price": 2.50, "output_price": 10.00, "cache_discount": 0.0 },
                "4": { "name": "gpt-4o-mini", "provider": "openai", "batch_size": 12, "temperature": 0.02, "input_price": 0.15, "output_price": 0.60, "cache_discount": 0.0 },
                "5": { "name": "deepseek-chat", "provider": "deepseek", "batch_size": 20, "temperature": 0.0, "input_price": 0.28, "output_price": 0.42, "cache_discount": 90.0 },
                "6": { "name": "local-model", "provider": "lmstudio", "batch_size": 10, "temperature": 0.0, "input_price": 0.0, "output_price": 1000000.0, "cache_discount": 0.0 },
                "7": { "name": "gpt-5-nano", "provider": "openai", "batch_size": 20, "temperature": 1.0, "input_price": 0.05, "output_price": 0.4, "cache_discount": 90.0 }
            }
        }

    def load_settings(self):
        if not os.path.exists(self.filename):
            self.config = self.load_defaults()
            self.save_settings()
        else:
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                
                # Dynamic update: ensure any existing models in JSON have the cache_discount field
                defaults = self.load_defaults()
                changed = False
                
                if "translation" not in self.config:
                    self.config["translation"] = defaults["translation"]
                    changed = True
                    
                for k, model in self.config["models"].items():
                    if "cache_discount" not in model:
                        # If it's a known model, take its default. Otherwise 90 for deepseek/gpt5, 0 for others.
                        if k in defaults["models"]:
                            model["cache_discount"] = defaults["models"][k]["cache_discount"]
                        else:
                            name_lower = model.get("name", "").lower()
                            if "deepseek" in name_lower or "gpt-5" in name_lower:
                                model["cache_discount"] = 90.0
                            else:
                                model["cache_discount"] = 0.0
                        changed = True
                if changed:
                    self.save_settings()
            except Exception:
                self.config = self.load_defaults()
                
    def save_settings(self):
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving settings: {e}")


SETTINGS = SettingsManager()
