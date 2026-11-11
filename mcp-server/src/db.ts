import { Client } from 'pg';

export type Chunk = {
  ordinal: number;
  text: string;
  start_ms: number | null;
  end_ms: number | null;
  timing_precision: string;
};
export type Job = {
  job_id: string;
  status: string;
  step: string | null;
  error_code: string | null;
  created_at: string;
  title: string | null;
  content_available: boolean;
};
export type Summary = Job & {
  summary: string | null;
  action_items: string | null;
  key_decisions: string | null;
  open_questions: string | null;
  truncated_fields: string[];
};
export type Reader = {
  list(limit: number, after?: { created_at: string; job_id: string }): Promise<Job[]>;
  status(jobId: string): Promise<Job | null>;
  summary(jobId: string): Promise<Summary | null>;
  transcript(jobId: string, limit: number, afterOrdinal: number): Promise<{ status: string; content_available: boolean; chunks: Chunk[] } | null>;
};

export function createReader(connectionString: string, schema: 'ava_mcp' | 'ava_mcp_preview' = 'ava_mcp'): Reader {
  if (schema !== 'ava_mcp' && schema !== 'ava_mcp_preview') throw new Error('Invalid database schema');
  const jobs = `"${schema}".shared_jobs`;
  const chunks = `"${schema}".shared_chunks`;
  const fields = `job_id::text, status, step, error_code, to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS created_at, title, content_available`;
  async function query<T>(sql: string, params: unknown[]): Promise<T[]> {
    const client = new Client({ connectionString, connectionTimeoutMillis: 5000, query_timeout: 7000 });
    try {
      await client.connect();
      return (await client.query(sql, params)).rows as T[];
    } finally {
      await client.end();
    }
  }
  return {
    list: (limit, after) => query<Job>(`SELECT ${fields} FROM ${jobs} j
      WHERE ($2::timestamptz IS NULL OR (j.created_at, j.job_id) < ($2::timestamptz, $3::uuid))
      ORDER BY j.created_at DESC, j.job_id DESC LIMIT $1`, [limit, after?.created_at ?? null, after?.job_id ?? null]),
    async status(jobId) {
      return (await query<Job>(`SELECT ${fields} FROM ${jobs} WHERE job_id = $1::uuid`, [jobId]))[0] ?? null;
    },
    async summary(jobId) {
      return (await query<Summary>(`SELECT ${fields}, summary, action_items, key_decisions, open_questions, truncated_fields FROM ${jobs} WHERE job_id = $1::uuid`, [jobId]))[0] ?? null;
    },
    async transcript(jobId, limit, afterOrdinal) {
      const rows = await query<{ status: string; content_available: boolean; chunks: Chunk[] }>(
        `SELECT j.status, j.content_available, COALESCE(c.chunks, '[]'::json) AS chunks FROM ${jobs} j LEFT JOIN LATERAL (SELECT json_agg(row_to_json(page) ORDER BY page.ordinal) AS chunks FROM (SELECT ordinal, text, start_ms, end_ms, timing_precision FROM ${chunks} WHERE job_id = j.job_id AND ordinal > $3 ORDER BY ordinal LIMIT $2) page) c ON true WHERE j.job_id = $1::uuid`,
        [jobId, limit, afterOrdinal],
      );
      return rows[0] ?? null;
    },
  };
}
