import type { Rubric } from "./types";
import { Field } from "./ui";

export function RubricEditor({
  value,
  onChange,
}: {
  value: Rubric | null;
  onChange: (value: Rubric | null) => void;
}) {
  return (
    <section className="rubric-editor">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) =>
            onChange(
              event.target.checked
                ? {
                    max_score: 0,
                    criteria: "",
                    aggregation: "none",
                    dimensions: [],
                  }
                : null,
            )
          }
        />
        设置数值评分标准
      </label>
      {value && (
        <>
          <div className="form-row">
            <Field label="评分满分">
              <input
                type="number"
                min="0.01"
                required
                step="any"
                value={value.max_score || ""}
                onChange={(event) =>
                  onChange({ ...value, max_score: Number(event.target.value) })
                }
              />
            </Field>
            <Field label="维度加总方式">
              <select
                value={value.aggregation}
                onChange={(event) =>
                  onChange({
                    ...value,
                    aggregation: event.target.value as Rubric["aggregation"],
                  })
                }
              >
                <option value="none">维度不加总</option>
                <option value="sum">维度加总为总分</option>
              </select>
            </Field>
          </div>
          <Field label="评分标准说明">
            <textarea
              value={value.criteria}
              onChange={(event) =>
                onChange({ ...value, criteria: event.target.value })
              }
            />
          </Field>
          {value.dimensions.map((dimension, index) => (
            <div className="form-row" key={index}>
              <Field label={`评分维度 ${index + 1}`}>
                <input
                  required
                  value={dimension.name}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      dimensions: value.dimensions.map((item, number) =>
                        number === index
                          ? { ...item, name: event.target.value }
                          : item,
                      ),
                    })
                  }
                />
              </Field>
              <Field label="维度满分">
                <div className="actions">
                  <input
                    type="number"
                    min="0.01"
                    required
                    step="any"
                    value={dimension.max_score || ""}
                    onChange={(event) =>
                      onChange({
                        ...value,
                        dimensions: value.dimensions.map((item, number) =>
                          number === index
                            ? { ...item, max_score: Number(event.target.value) }
                            : item,
                        ),
                      })
                    }
                  />
                  <button
                    type="button"
                    onClick={() =>
                      onChange({
                        ...value,
                        dimensions: value.dimensions.filter(
                          (_, number) => number !== index,
                        ),
                      })
                    }
                  >
                    移除维度
                  </button>
                </div>
              </Field>
            </div>
          ))}
          <button
            type="button"
            onClick={() =>
              onChange({
                ...value,
                dimensions: [...value.dimensions, { name: "", max_score: 0 }],
              })
            }
          >
            添加评分维度
          </button>
          {value.aggregation === "sum" &&
            Math.abs(
              value.dimensions.reduce((sum, item) => sum + item.max_score, 0) -
                value.max_score,
            ) > 0.000001 && (
              <p className="danger-text">维度满分之和必须等于总满分。</p>
            )}
        </>
      )}
    </section>
  );
}
