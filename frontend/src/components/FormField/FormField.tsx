import {
  Children,
  cloneElement,
  isValidElement,
  useId,
  type AriaAttributes,
  type ReactElement,
  type ReactNode,
} from "react";

type FieldControlProps = {
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: AriaAttributes["aria-invalid"];
  "aria-required"?: AriaAttributes["aria-required"];
};

type FormFieldProps = {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactElement<FieldControlProps>;
  suffix?: ReactNode;
};

export function FormField({ label, hint, error, required, children, suffix }: FormFieldProps) {
  const generatedId = useId();
  const control = Children.only(children);

  if (!isValidElement<FieldControlProps>(control)) {
    throw new Error("FormField requires a single form control child.");
  }

  const controlId = control.props.id ?? `field-${generatedId.replace(/:/g, "")}`;
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy = [control.props["aria-describedby"], hintId, errorId]
    .filter(Boolean)
    .join(" ") || undefined;

  return (
    <div className="form-field">
      <label className="form-field__label" htmlFor={controlId}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </label>
      <div className="form-field__control">
        {cloneElement(control, {
          id: controlId,
          "aria-describedby": describedBy,
          "aria-invalid": error ? true : control.props["aria-invalid"],
          "aria-required": required ? true : control.props["aria-required"],
        })}
        {suffix ? <span className="form-field__suffix">{suffix}</span> : null}
      </div>
      {hint ? <p className="form-field__hint" id={hintId}>{hint}</p> : null}
      {error ? <p className="form-field__error" id={errorId}>{error}</p> : null}
    </div>
  );
}
