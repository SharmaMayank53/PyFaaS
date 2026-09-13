import { NextResponse, type NextRequest } from "next/server";

const PROTECTED_ROUTES = [
  "/",
  "/cluster",
  "/executions",
  "/functions",
  "/logs",
  "/keys",
  "/schedules",
];

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_ROUTES.some((route) => {
    if (route === "/") return pathname === "/";
    return pathname === route || pathname.startsWith(`${route}/`);
  });
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (!isProtectedPath(pathname)) {
    return NextResponse.next();
  }

  const token = request.cookies.get("sopm_token")?.value;
  if (token) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    "/",
    "/cluster/:path*",
    "/executions/:path*",
    "/functions/:path*",
    "/logs/:path*",
    "/keys/:path*",
    "/schedules/:path*",
  ],
};






