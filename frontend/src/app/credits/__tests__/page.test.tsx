import { screen } from "@testing-library/react";
import { mockFetch, renderWithProviders } from "@/test-utils";
import CreditsPage from "@/app/credits/page";
import { PhotoCredit } from "@/types/config";

const CREDITS: PhotoCredit[] = [
  {
    listing_key: "stapler",
    listing_title: "Stapler",
    photo_title: "Red stapler",
    creator: "Jane Photographer",
    creator_url: "https://example.com/jane",
    license: "by",
    license_version: "2.0",
    license_url: "https://creativecommons.org/licenses/by/2.0/",
    source_url: "https://example.com/photo/1",
  },
  {
    listing_key: "dumbbells",
    listing_title: "Dumbbells",
    photo_title: null,
    creator: null,
    creator_url: null,
    license: "cc0",
    license_version: "1.0",
    license_url: "https://creativecommons.org/publicdomain/zero/1.0/",
    source_url: "https://example.com/photo/2",
  },
];

describe("CreditsPage", () => {
  it("lists each photo with its creator, source and license", async () => {
    mockFetch(CREDITS);
    renderWithProviders(<CreditsPage />);

    expect(await screen.findByText("Stapler")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Red stapler" })).toHaveAttribute(
      "href",
      "https://example.com/photo/1",
    );
    expect(screen.getByRole("link", { name: "Jane Photographer" })).toHaveAttribute(
      "href",
      "https://example.com/jane",
    );
    expect(screen.getByRole("link", { name: "CC BY 2.0" })).toBeInTheDocument();
    // Missing title/creator degrade gracefully
    expect(screen.getByRole("link", { name: "Photo" })).toHaveAttribute(
      "href",
      "https://example.com/photo/2",
    );
    expect(screen.getByRole("link", { name: "CC0 1.0" })).toBeInTheDocument();
  });

  it("shows an error when credits can't load", async () => {
    mockFetch({ detail: "boom" }, { ok: false, status: 500 });
    renderWithProviders(<CreditsPage />);
    expect(await screen.findByText(/Couldn.t load the photo credits/)).toBeInTheDocument();
  });
});
