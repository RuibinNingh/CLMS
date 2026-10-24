import { useEffect, useState } from "react";
import { Field } from "./ui";

function lines(text: string) {
  return text
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}
export function ListField({
  label,
  value,
  onChange,
  max,
}: {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  max?: number;
}) {
  const [text, setText] = useState(value.join("\n"));
  const serialized = JSON.stringify(value);
  useEffect(() => {
    if (JSON.stringify(lines(text)) !== serialized) setText(value.join("\n"));
  }, [serialized]);
  return (
    <Field label={label} hint={max ? `最多 ${max} 项。` : undefined}>
      <textarea
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          onChange(lines(event.target.value));
        }}
      />
      {max && value.length > max ? (
        <small className="danger-text">请保留最重要的 {max} 项。</small>
      ) : null}
    </Field>
  );
}
