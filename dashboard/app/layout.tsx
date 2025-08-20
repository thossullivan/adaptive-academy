import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "Learning Dashboard",
  description: "A modern dashboard for learning management built with Next.js 14",
  keywords: ["learning", "dashboard", "education", "next.js"],
  authors: [
    {
      name: "Learning Dashboard Team",
    },
  ],
  viewport: "width=device-width, initial-scale=1",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        {/* Enable better mobile tap highlights */}
        <div className="min-h-screen bg-background antialiased">
          {children}
        </div>
      </body>
    </html>
  )
}