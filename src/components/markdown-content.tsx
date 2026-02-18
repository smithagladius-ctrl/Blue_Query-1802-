'use client';

import ReactMarkdown from 'react-markdown';
import { ChevronsRight } from 'lucide-react';

type MarkdownTable = {
  headers: string[];
  rows: string[][];
};

type Segment =
  | { type: 'markdown'; content: string }
  | { type: 'table'; table: MarkdownTable };

const markdownComponents: object = {
  h3: ({ node, ...props }: any) => <h3 className="mt-4 mb-2 text-lg font-semibold" {...props} />,
  ul: ({ node, ...props }: any) => <ul className="list-none space-y-2" {...props} />,
  li: ({ node, ...props }: any) => (
    <li className="flex items-start">
      <ChevronsRight className="mr-2 mt-1 h-4 w-4 flex-shrink-0 text-primary" />
      <span {...props} />
    </li>
  ),
  blockquote: ({ node, ...props }: any) => (
    <blockquote className="mt-2 border-l-2 border-primary pl-4 italic text-muted-foreground" {...props} />
  ),
  p: ({ node, ...props }: any) => <p className="mb-2" {...props} />,
  code: ({ inline, className, children, ...props }: any) =>
    inline ? (
      <code className="rounded bg-muted px-1.5 py-0.5 text-xs" {...props}>
        {children}
      </code>
    ) : (
      <pre className="my-2 overflow-x-auto rounded-md bg-muted p-3 text-xs">
        <code className={className} {...props}>
          {children}
        </code>
      </pre>
    ),
};

function isTableSeparator(line: string): boolean {
  const trimmed = line.trim();
  return /^\|?[\s:-]+\|[\s|:-]*\|?$/.test(trimmed);
}

function splitTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function parseSegments(text: string): Segment[] {
  const lines = text.split('\n');
  const segments: Segment[] = [];
  let markdownBuffer: string[] = [];
  let i = 0;

  const flushMarkdown = () => {
    const content = markdownBuffer.join('\n').trim();
    if (content) {
      segments.push({ type: 'markdown', content });
    }
    markdownBuffer = [];
  };

  while (i < lines.length) {
    const line = lines[i];
    const next = i + 1 < lines.length ? lines[i + 1] : '';
    const looksLikeHeader = line.includes('|');
    const looksLikeTable = looksLikeHeader && isTableSeparator(next);

    if (!looksLikeTable) {
      markdownBuffer.push(line);
      i += 1;
      continue;
    }

    flushMarkdown();
    const headers = splitTableRow(line);
    i += 2;
    const rows: string[][] = [];

    while (i < lines.length && lines[i].includes('|')) {
      const row = splitTableRow(lines[i]);
      if (row.length > 0 && !(row.length === 1 && row[0] === '')) {
        rows.push(row);
      }
      i += 1;
    }

    segments.push({ type: 'table', table: { headers, rows } });
  }

  flushMarkdown();
  return segments;
}

function normalizeRow(row: string[], width: number): string[] {
  if (row.length === width) return row;
  if (row.length > width) return row.slice(0, width);
  return [...row, ...Array(width - row.length).fill('')];
}

export function MarkdownContent({ content }: { content: string }) {
  const segments = parseSegments(content || '');

  return (
    <div className="space-y-3">
      {segments.map((segment, index) => {
        if (segment.type === 'markdown') {
          return (
            <ReactMarkdown key={`md-${index}`} components={markdownComponents}>
              {segment.content}
            </ReactMarkdown>
          );
        }

        const { headers, rows } = segment.table;
        const width = headers.length;
        return (
          <div key={`tbl-${index}`} className="my-2 overflow-x-auto rounded-md border border-border">
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/60">
                <tr>
                  {headers.map((h, idx) => (
                    <th key={idx} className="border-b border-border px-3 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => (
                  <tr key={rowIndex} className="odd:bg-background even:bg-muted/20">
                    {normalizeRow(row, width).map((cell, cellIndex) => (
                      <td key={cellIndex} className="border-b border-border px-3 py-2 align-top">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
