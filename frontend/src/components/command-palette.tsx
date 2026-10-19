import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const commands = [
  { label: "Search records", path: "/search", keywords: "find documents requests" },
  { label: "Open requests", path: "/requests", keywords: "public records queue" },
  { label: "Review audit log", path: "/audit-log", keywords: "compliance events history" },
  { label: "Manage sources", path: "/sources", keywords: "connectors documents ingestion" },
  { label: "Open settings", path: "/settings", keywords: "password account system" },
];

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const filteredCommands = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((command) =>
      `${command.label} ${command.keywords}`.toLowerCase().includes(needle)
    );
  }, [query]);

  const runCommand = (path: string) => {
    navigate(path);
    onOpenChange(false);
    setQuery("");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label="Command palette" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Command palette</DialogTitle>
          <DialogDescription>
            Jump to common operator work without leaving the keyboard.
          </DialogDescription>
        </DialogHeader>
        <Input
          aria-label="Command search"
          placeholder="Type a command"
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="grid gap-1">
          {filteredCommands.map((command) => (
            <button
              key={command.path}
              type="button"
              className="rounded-md px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              onClick={() => runCommand(command.path)}
            >
              {command.label}
            </button>
          ))}
          {!filteredCommands.length && (
            <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              No matching command. Try "requests", "audit", "sources", or "settings".
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
