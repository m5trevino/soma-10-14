import { createSignal } from "solid-js";

export function useDeckStore() {
  const [deck, setDeck] = createSignal<any[]>([]);

  return {
    deck,
    setDeck,
    addDeck: (entry: any) => setDeck([...deck(), entry]),
    removeDeck: (index: number) =>
      setDeck(deck().filter((_: any, i: number) => i !== index)),
    updateDeck: (index: number, entry: any) => {
      const newDeck = [...deck()];
      newDeck[index] = entry;
      setDeck(newDeck);
    },
  };
}
