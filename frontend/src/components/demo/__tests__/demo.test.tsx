import { screen, waitFor, renderHook } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { createTestQueryClient, renderWithProviders } from "@/test-utils";
import { useAppConfig } from "@/hooks/useAppConfig";
import { DEFAULT_APP_CONFIG } from "@/lib/config-api";
import { DemoBanner, formatTimeUntil } from "@/components/demo/DemoBanner";
import { DemoPersonaPicker } from "@/components/demo/DemoPersonaPicker";
import { SearchFilters } from "@/components/listings/SearchFilters";
import { AppConfig } from "@/types/config";

const DEMO_CONFIG: AppConfig = {
  demo: {
    enabled: true,
    next_reset_at: new Date(Date.now() + (3 * 60 + 12) * 60_000).toISOString(),
    reset_interval_hours: 6,
    personas: [
      {
        key: "maya",
        name: "Maya Rodriguez",
        username: "maya_r",
        role: "seller",
        blurb: "Sells stuff.",
      },
      {
        key: "jordan",
        name: "Jordan Lee",
        username: "jordan_l",
        role: "buyer",
        blurb: "Buys stuff.",
      },
    ],
  },
  ai: { semantic_search: true, assistant: true, generate_description: true },
};

const TOKEN = {
  access_token: "demo-token",
  token_type: "bearer",
  user: {
    id: "u1",
    username: "maya_r",
    email: "maya_r@example.com",
    is_verified: true,
    role: "user",
    created_at: "2026-01-01T00:00:00Z",
  },
};

/** Route fetch by URL: /config and /auth/demo/* answer; anything else 404s. */
function mockApi(config: AppConfig | null) {
  const fetchMock = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const respond = (body: unknown, ok = true, status = 200) =>
      Promise.resolve({
        ok,
        status,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
        headers: new Headers(),
      });
    if (url.endsWith("/config")) {
      return config ? respond(config) : respond({ detail: "Not Found" }, false, 404);
    }
    if (url.includes("/auth/demo/") && init?.method === "POST") {
      return respond(TOKEN);
    }
    return respond({ detail: "Not Found" }, false, 404);
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  localStorage.clear();
});

describe("useAppConfig", () => {
  it("falls back to no demo and AI shown when /config is missing", async () => {
    const fetchMock = mockApi(null);
    const { result } = renderHook(() => useAppConfig(), { wrapper });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current.isDemo).toBe(false);
    expect(result.current.ai).toEqual(DEFAULT_APP_CONFIG.ai);
  });

  it("returns the backend config once loaded", async () => {
    mockApi(DEMO_CONFIG);
    const { result } = renderHook(() => useAppConfig(), { wrapper });
    await waitFor(() => expect(result.current.isDemo).toBe(true));
    expect(result.current.demo.personas).toHaveLength(2);
  });
});

describe("DemoBanner", () => {
  it("renders nothing outside demo mode", async () => {
    const fetchMock = mockApi({ ...DEMO_CONFIG, demo: { ...DEMO_CONFIG.demo, enabled: false } });
    const { container } = renderWithProviders(<DemoBanner />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the reset countdown and source link in demo mode", async () => {
    mockApi(DEMO_CONFIG);
    renderWithProviders(<DemoBanner />);
    expect(await screen.findByText(/resets in 3h 1[12]m/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View source" })).toHaveAttribute(
      "href",
      "https://github.com/xZanderBR/Aztec-List",
    );
  });

  it("formats time until reset", () => {
    const now = Date.parse("2026-01-01T00:00:00Z");
    expect(formatTimeUntil("2026-01-01T02:05:00Z", now)).toBe("2h 5m");
    expect(formatTimeUntil("2026-01-01T00:09:00Z", now)).toBe("9m");
    expect(formatTimeUntil("2025-12-31T23:00:00Z", now)).toBe("0m");
  });
});

describe("DemoPersonaPicker", () => {
  it("logs in as the chosen persona", async () => {
    const fetchMock = mockApi(DEMO_CONFIG);
    const user = userEvent.setup();
    renderWithProviders(<DemoPersonaPicker />);

    await user.click(await screen.findByRole("button", { name: /Maya Rodriguez/ }));

    await waitFor(() => expect(localStorage.getItem("auth_token")).toBe("demo-token"));
    const demoCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/auth/demo/"));
    expect(String(demoCall?.[0])).toMatch(/\/auth\/demo\/maya$/);
    expect(demoCall?.[1]).toMatchObject({ method: "POST" });
  });

  it("renders nothing outside demo mode", async () => {
    const fetchMock = mockApi(null);
    const { container } = renderWithProviders(<DemoPersonaPicker />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("AI feature flags", () => {
  it("hides the Smart search toggle when semantic search is off", async () => {
    mockApi({ ...DEMO_CONFIG, ai: { ...DEMO_CONFIG.ai, semantic_search: false } });
    renderWithProviders(<SearchFilters />);
    await waitFor(() => expect(screen.queryAllByText("Smart search (AI)")).toHaveLength(0));
    expect(screen.getAllByText("Category").length).toBeGreaterThan(0);
  });

  it("shows the Smart search toggle when semantic search is on", async () => {
    mockApi(DEMO_CONFIG);
    renderWithProviders(<SearchFilters />);
    expect((await screen.findAllByText("Smart search (AI)")).length).toBeGreaterThan(0);
  });
});

describe("getAppConfig hardening", () => {
  it("falls back to defaults when /config returns an unexpected shape", async () => {
    const fetchMock = jest.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ id: "u1", username: "someone" }),
        headers: new Headers(),
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;
    const { result } = renderHook(() => useAppConfig(), { wrapper });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(result.current.isDemo).toBe(false);
    expect(result.current.ai.assistant).toBe(true);
  });
});
