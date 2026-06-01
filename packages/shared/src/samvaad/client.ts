export type SamvaadClientOpts = {
  apiKey: string;
  baseUrl: string;
  fetchImpl?: typeof fetch;
};

export class SamvaadClient {
  private fetchImpl: typeof fetch;
  constructor(public opts: SamvaadClientOpts) {
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }
  async post<T>(path: string, body: unknown): Promise<T> {
    const res = await this.fetchImpl(`${this.opts.baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${this.opts.apiKey}` },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`samvaad ${path} ${res.status}: ${await res.text()}`);
    return (await res.json()) as T;
  }
}
