"use client";

import { useState, FormEvent } from "react";
import Image from "next/image";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Product {
  title: string;
  price: number;
  price_display: string;
  mrp?: number | null;
  discount_pct?: number | null;
  url?: string | null;
  image_url?: string | null;
}

interface ApiResponse {
  ok: boolean;
  query: string;
  matched_query?: string;
  fuzzy_corrected?: boolean;
  pincode?: string;
  pincode_unverified?: boolean;
  products?: Product[];
  scraped_at?: string;
  reason?: string;
  message?: string;
}

// ---------------------------------------------------------------------------
// UI sub-components
// ---------------------------------------------------------------------------

function Spinner() {
  return (
    <div className="flex flex-col items-center gap-3 py-10">
      <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-gray-500 text-sm">Searching Flipkart...</p>
    </div>
  );
}

function FuzzyBanner({ matchedQuery }: { matchedQuery: string }) {
  return (
    <div className="mb-4 px-4 py-2 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
      Showing results for <strong>{matchedQuery}</strong>
    </div>
  );
}

function ResultsTable({ products }: { products: Product[] }) {
  return (
    <div className="overflow-x-auto rounded-2xl shadow-md bg-white">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 text-left text-xs text-gray-500 uppercase tracking-wide">
            <th className="px-4 py-3">#</th>
            <th className="px-4 py-3">Product</th>
            <th className="px-4 py-3 whitespace-nowrap">Price</th>
            <th className="px-4 py-3 whitespace-nowrap">MRP</th>
            <th className="px-4 py-3 whitespace-nowrap">Discount</th>
            <th className="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody>
          {products.map((product, idx) => (
            <tr
              key={product.url ?? idx}
              className="border-b border-gray-50 last:border-0 hover:bg-gray-50 transition-colors"
            >
              <td className="px-4 py-4 text-gray-400 font-medium align-top">{idx + 1}</td>
              <td className="px-4 py-4 align-top">
                <div className="flex items-start gap-3">
                  {product.image_url && (
                    <div className="flex-shrink-0 w-12 h-12 relative rounded-lg overflow-hidden bg-gray-100">
                      <Image
                        src={product.image_url}
                        alt={product.title}
                        fill
                        sizes="48px"
                        className="object-contain p-1"
                        unoptimized
                      />
                    </div>
                  )}
                  <span className="text-gray-900 font-medium leading-snug max-w-xs">
                    {product.title}
                  </span>
                </div>
              </td>
              <td className="px-4 py-4 whitespace-nowrap align-top">
                <span className="text-green-700 font-bold text-base">{product.price_display}</span>
              </td>
              <td className="px-4 py-4 whitespace-nowrap align-top">
                {product.mrp && product.mrp !== product.price ? (
                  <span className="text-gray-400 line-through text-sm">
                    &#8377;{product.mrp.toLocaleString()}
                  </span>
                ) : (
                  <span className="text-gray-300">—</span>
                )}
              </td>
              <td className="px-4 py-4 whitespace-nowrap align-top">
                {product.discount_pct && product.discount_pct > 0 ? (
                  <span className="text-xs font-medium bg-green-100 text-green-700 px-2 py-1 rounded-full">
                    {product.discount_pct}% off
                  </span>
                ) : (
                  <span className="text-gray-300">—</span>
                )}
              </td>
              <td className="px-4 py-4 whitespace-nowrap align-top">
                {product.url && (
                  <a
                    href={product.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:text-blue-800 hover:underline text-sm font-medium"
                  >
                    View on Flipkart &rarr;
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-2xl p-6 text-center">
      <p className="text-red-700 font-medium">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    setError(null);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 35_000);

    try {
      const res = await fetch("/api/price", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim() }),
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (!res.ok) {
        setError("Server error. Please try again.");
        return;
      }
      const data: ApiResponse = await res.json();
      setResult(data);
    } catch (err: unknown) {
      clearTimeout(timeout);
      if (err instanceof Error && err.name === "AbortError") {
        setError("Request timed out. Flipkart took too long to respond.");
      } else {
        setError("Network error. Make sure the backend is running.");
      }
    } finally {
      setLoading(false);
    }
  }

  const noResults = result && !result.ok && result.reason === "no_results";
  const scrapeFailed = result && !result.ok && result.reason === "scrape_failed";

  return (
    <main className="min-h-screen flex flex-col items-center justify-start pt-16 px-4 pb-16">
      {/* Header */}
      <div className="mb-8 text-center">
        <div className="inline-flex items-center gap-2 bg-blue-600 text-white text-xs font-bold px-3 py-1 rounded-full mb-3">
          &#9889; Flipkart
        </div>
        <h1 className="text-3xl font-bold text-gray-900">Price Checker</h1>
        <p className="text-gray-500 mt-1 text-sm">Search products and prices on Flipkart</p>
      </div>

      {/* Search form */}
      <form onSubmit={handleSubmit} className="w-full max-w-md mb-6">
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Try: laptop, phone, headphones..."
            className="flex-1 border border-gray-300 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-pink-400 bg-white shadow-sm"
            disabled={loading}
            aria-label="Product search"
          />
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="bg-pink-600 hover:bg-pink-700 disabled:opacity-50 text-white font-semibold px-5 py-3 rounded-xl text-sm transition-colors shadow-sm"
          >
            Get price
          </button>
        </div>
      </form>

      {/* Results area */}
      <div className="w-full max-w-4xl">
        {loading && <Spinner />}

        {!loading && result?.ok && result.products && result.products.length > 0 && (
          <>
            {result.fuzzy_corrected && result.matched_query && (
              <FuzzyBanner matchedQuery={result.matched_query} />
            )}
            <ResultsTable products={result.products} />
          </>
        )}

        {!loading && noResults && (
          <ErrorCard message="No products found on Flipkart for this query." />
        )}

        {!loading && scrapeFailed && (
          <ErrorCard message={result?.message ?? "Something went wrong. Try again."} />
        )}

        {!loading && error && <ErrorCard message={error} />}
      </div>
    </main>
  );
}
