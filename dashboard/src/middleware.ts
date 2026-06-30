import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';

// Public routes that must NOT be protected: the sign-in and sign-up flows
// (catch-all routes from Clerk's <SignIn />/<SignUp /> components).
const isPublicRoute = createRouteMatcher([
  '/sign-in(.*)',
  '/sign-up(.*)',
]);

export default clerkMiddleware(async (auth, request) => {
  // Everything except the public sign-in/sign-up routes requires auth.
  // In middleware, auth.protect() redirects signed-out users to the sign-in
  // page (for document requests) or returns a 404 for API requests.
  if (!isPublicRoute(request)) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
};
