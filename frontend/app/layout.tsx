import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flipkart Minutes Price",
  description: "Check live prices on Flipkart Minutes (hyperlocal grocery delivery)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        {children}
      </body>
    </html>
  );
}
