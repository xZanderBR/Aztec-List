import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Photo Credits",
};

export default function CreditsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
