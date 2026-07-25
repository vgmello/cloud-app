import { hero } from "./hero";

export interface Section {
  readonly id: string;
  render(): string;
}

export const SECTIONS: readonly Section[] = [hero];
