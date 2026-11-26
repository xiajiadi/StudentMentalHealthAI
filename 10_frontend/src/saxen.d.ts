declare module 'saxen' {
  export class Parser {
    on(event: 'error', handler: (error: Error) => void): void
    on(event: 'openTag', handler: (
      name: string,
      attributes: () => Record<string, string | undefined>,
      decode: (value: string) => string,
    ) => void): void
    parse(xml: string): void
  }
}
