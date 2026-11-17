/** Public runtime config from `GET /config` (backend `app/schemas/demo.py`). */

export interface DemoPersona {
  key: string;
  name: string;
  username: string;
  role: "seller" | "buyer" | "moderator" | string;
  blurb: string;
}

export interface DemoConfig {
  enabled: boolean;
  next_reset_at: string | null;
  reset_interval_hours?: number | null;
  personas: DemoPersona[];
}

export interface AIFeatures {
  semantic_search: boolean;
  assistant: boolean;
  generate_description: boolean;
}

export interface AppConfig {
  demo: DemoConfig;
  ai: AIFeatures;
}
