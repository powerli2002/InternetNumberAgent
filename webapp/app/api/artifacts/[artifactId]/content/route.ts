import { NextRequest, NextResponse } from "next/server";

type RouteContext = {
  params: Promise<{
    artifactId: string;
  }>;
};

function resolveBackendBase(request: NextRequest): string {
  const configured =
    process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "";
  if (configured.trim()) {
    return configured.trim().replace(/\/$/, "");
  }
  const url = new URL(request.url);
  return `${url.protocol}//${url.hostname}:2026`;
}

export async function GET(request: NextRequest, context: RouteContext) {
  const { artifactId } = await context.params;
  const upstreamUrl = `${resolveBackendBase(request)}/api/artifacts/${artifactId}/content`;
  const requestHeaders: Record<string, string> = {
    cookie: request.headers.get("cookie") || "",
    accept: request.headers.get("accept") || "*/*"
  };
  const range = request.headers.get("range");
  if (range && range.trim()) {
    requestHeaders.range = range.trim();
  }
  const upstream = await fetch(upstreamUrl, {
    method: "GET",
    headers: requestHeaders,
    cache: "no-store"
  });

  if (!upstream.ok || !upstream.body) {
    return new NextResponse(await upstream.text(), {
      status: upstream.status || 502
    });
  }

  const responseHeaders = new Headers();
  const contentType = upstream.headers.get("content-type");
  const contentLength = upstream.headers.get("content-length");
  const disposition = upstream.headers.get("content-disposition");
  const lastModified = upstream.headers.get("last-modified");
  const etag = upstream.headers.get("etag");

  if (contentType) {
    responseHeaders.set("content-type", contentType);
  }
  if (contentLength) {
    responseHeaders.set("content-length", contentLength);
  }
  if (disposition) {
    responseHeaders.set("content-disposition", disposition.replace(/^attachment/i, "inline"));
  }
  if (lastModified) {
    responseHeaders.set("last-modified", lastModified);
  }
  if (etag) {
    responseHeaders.set("etag", etag);
  }
  responseHeaders.set("cache-control", "private, no-store");

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders
  });
}
