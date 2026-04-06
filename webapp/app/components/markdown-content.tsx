"use client";

import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

type MarkdownArtifact = {
  id: string;
  title: string;
  mime_type: string;
  contentUrl: string;
};

type MarkdownContentProps = {
  content: string;
  artifacts?: MarkdownArtifact[];
  onArtifactClick?: (artifactId: string) => void;
};

function isExternalHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

function getArtifactIdFromUrl(value: string): string {
  if (!value.startsWith("artifact://")) {
    return "";
  }
  return value.replace("artifact://", "").trim();
}

export function MarkdownContent({
  content,
  artifacts = [],
  onArtifactClick
}: MarkdownContentProps) {
  const artifactMap = new Map(artifacts.map((artifact) => [artifact.id, artifact]));
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        skipHtml
        components={{
          a: ({ href, children, ...props }) => {
            const safeHref = typeof href === "string" ? href : "";
            const artifactId = getArtifactIdFromUrl(safeHref);
            const artifact = artifactId ? artifactMap.get(artifactId) : null;
            if (artifact) {
              return (
                <button
                  type="button"
                  className="markdown-artifact-link"
                  onClick={() => onArtifactClick?.(artifact.id)}
                >
                  {children}
                </button>
              );
            }
            const external = isExternalHref(safeHref);
            return (
              <a
                {...props}
                href={safeHref || undefined}
                target={external ? "_blank" : undefined}
                rel={external ? "noreferrer noopener" : undefined}
              >
                {children}
              </a>
            );
          },
          table: ({ children, ...props }) => (
            <div className="markdown-table-wrap">
              <table {...props}>{children}</table>
            </div>
          ),
          img: ({ src, alt }) => {
            const safeSrc = typeof src === "string" ? src : "";
            const artifactId = getArtifactIdFromUrl(safeSrc);
            const artifact = artifactId ? artifactMap.get(artifactId) : null;
            if (artifact) {
              return (
                <button
                  type="button"
                  className="markdown-artifact-figure"
                  onClick={() => onArtifactClick?.(artifact.id)}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={artifact.contentUrl}
                    alt={alt || artifact.title}
                    className="markdown-artifact-image"
                  />
                  <span className="markdown-artifact-caption">
                    {alt || artifact.title}
                  </span>
                </button>
              );
            }
            if (!safeSrc) {
              return null;
            }
            return (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={safeSrc} alt={alt || ""} className="markdown-inline-image" />
            );
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
