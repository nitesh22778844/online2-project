/**
 * Frontend tests for the search page.
 * Uses Vitest + React Testing Library + jsdom.
 * fetch is mocked — no real network calls.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Home from "../app/page";

// Mock next/image so it renders a plain <img>
vi.mock("next/image", () => ({
  default: ({ src, alt }: { src: string; alt: string }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} />
  ),
}));

const SUCCESS_RESPONSE = {
  ok: true,
  query: "milk",
  matched_query: "milk",
  fuzzy_corrected: false,
  pincode: "560094",
  pincode_unverified: false,
  products: [
    {
      title: "Amul Gold Milk 500ml",
      price: 32,
      price_display: "₹32",
      mrp: 33,
      discount_pct: 3,
      url: "https://www.flipkart.com/amul-gold-milk/p/ABC123",
      image_url: "https://rukminim2.flixcart.com/image/amul.jpg",
    },
  ],
  scraped_at: "2026-04-25T10:00:00Z",
};

const FUZZY_RESPONSE = {
  ...SUCCESS_RESPONSE,
  query: "mlik",
  matched_query: "milk",
  fuzzy_corrected: true,
};

const NO_RESULTS_RESPONSE = {
  ok: false,
  query: "asdfgh",
  reason: "no_results",
  message: "No products found on Flipkart Minutes for this query.",
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("Search form", () => {
  it("renders the search input and button", () => {
    render(<Home />);
    expect(screen.getByRole("textbox", { name: /product search/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /get price/i })).toBeInTheDocument();
  });

  it("button is disabled when input is empty", () => {
    render(<Home />);
    const btn = screen.getByRole("button", { name: /get price/i });
    expect(btn).toBeDisabled();
  });

  it("button is enabled after typing", async () => {
    render(<Home />);
    const input = screen.getByRole("textbox");
    await userEvent.type(input, "milk");
    expect(screen.getByRole("button", { name: /get price/i })).not.toBeDisabled();
  });

  it("submits on Enter key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => SUCCESS_RESPONSE,
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);
    const input = screen.getByRole("textbox");
    await userEvent.type(input, "milk{Enter}");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/price",
      expect.objectContaining({ method: "POST" })
    );
  });
});

describe("Result card", () => {
  it("shows product price formatted correctly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => SUCCESS_RESPONSE,
    }));

    render(<Home />);
    await userEvent.type(screen.getByRole("textbox"), "milk");
    fireEvent.click(screen.getByRole("button", { name: /get price/i }));

    await waitFor(() => {
      expect(screen.getByText("₹32")).toBeInTheDocument();
    });
    expect(screen.getByText("Amul Gold Milk 500ml")).toBeInTheDocument();
    expect(screen.getByText("3% off")).toBeInTheDocument();
    expect(screen.getByText(/view on flipkart/i)).toBeInTheDocument();
  });

  it("shows discount badge when discount_pct > 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => SUCCESS_RESPONSE,
    }));

    render(<Home />);
    await userEvent.type(screen.getByRole("textbox"), "milk");
    fireEvent.click(screen.getByRole("button", { name: /get price/i }));

    await waitFor(() => expect(screen.getByText("3% off")).toBeInTheDocument());
  });

  it("shows fuzzy_corrected banner when fuzzy_corrected is true", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => FUZZY_RESPONSE,
    }));

    render(<Home />);
    await userEvent.type(screen.getByRole("textbox"), "mlik");
    fireEvent.click(screen.getByRole("button", { name: /get price/i }));

    await waitFor(() =>
      expect(screen.getByText(/showing results for/i)).toBeInTheDocument()
    );
    expect(screen.getByText("milk")).toBeInTheDocument();
  });

  it("shows no results message for unknown query", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => NO_RESULTS_RESPONSE,
    }));

    render(<Home />);
    await userEvent.type(screen.getByRole("textbox"), "asdfgh");
    fireEvent.click(screen.getByRole("button", { name: /get price/i }));

    await waitFor(() =>
      expect(screen.getByText(/no products found/i)).toBeInTheDocument()
    );
  });
});
