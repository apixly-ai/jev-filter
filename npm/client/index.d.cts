export interface AnalysisSpec {
  mode?: 'filter' | 'choose' | 'analyze' | 'passthrough';
  context?: unknown;
  required_context?: string[];
  required_record_fields?: string[];
  requirements?: {id:string; statement:string; expected:boolean}[];
  questions?: Record<string, unknown>;
  uncertainty?: Record<string, unknown>;
  contract?: {id:string; version:string; fingerprint?:string};
  [field:string]: unknown;
}
export interface EvidencePacket {
  ok?: boolean;
  complete?: boolean;
  selected_ids?: string[];
  review_ids?: string[];
  archive?: string;
  receipt?: string;
  [field:string]: unknown;
}
export interface Options {
  task:string;
  analysis?:AnalysisSpec;
  signal?:AbortSignal;
  budgetChars?:number;
  workers?:number;
}
export interface CodeOptions extends Options {root?:string; query?:string; expandCallers?:boolean}
export interface DiffOptions extends Options {root?:string; base?:string; head?:string; staged?:boolean; unstaged?:boolean}
export interface ClientResult {packet:EvidencePacket; exitCode:0|2}
export interface Client {
  query(records:readonly {id?:string; text:string; [field:string]:unknown}[], options:Options):Promise<ClientResult>;
  codeSearch(pattern:string, options:CodeOptions):Promise<ClientResult>;
  triage(events:readonly Record<string,unknown>[], options:Options & {groupBy?:string}):Promise<ClientResult>;
  diffReview(options:DiffOptions):Promise<ClientResult>;
}
export function createClient(configuration?: {
  command?:readonly string[];
  cwd?:string;
  env?:Record<string,string>;
  timeoutMs?:number;
  maxOutputBytes?:number;
}):Client;
export class JevFilterError extends Error {code:string; exitCode?:number}
