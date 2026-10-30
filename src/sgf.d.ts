declare module '@sabaki/sgf' {
  export interface SgfNode {
    data: Record<string, string[]>
    children: SgfNode[]
  }
  export interface Token {
    type: string
    value: string
    row: number
    col: number
  }
  export function tokenize(contents: string): Token[]
  export function parseTokens(tokens: Token[]): SgfNode[]
}
