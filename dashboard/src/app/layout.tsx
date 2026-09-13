import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/layout/Providers";

export const metadata: Metadata = {
  title: "PyFaaS — Operations Dashboard",
  description: "Python Functions-as-a-Service Platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}


