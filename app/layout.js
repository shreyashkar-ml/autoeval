import "./globals.css";

export const metadata = {
  title: "Autoexp — experimentation infrastructure for coding agents",
  description:
    "Run reproducible experiments, preserve evidence, compare results, and steer autonomous research from your coding agent.",
  metadataBase: new URL("https://autoexp.dev"),
  openGraph: {
    title: "Autoexp",
    description: "Local-first experimentation infrastructure for coding agents.",
    url: "https://autoexp.dev",
    siteName: "Autoexp",
    type: "website",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
