// Both arguments are Vue refs; callers can render the error persistently.
export function createResourceLoader(data, error, fetchData, emptyValue) {
  let generation = 0;
  return async () => {
    const current = ++generation;
    try {
      const value = await fetchData();
      if (current !== generation) return;
      data.value = value;
      error.value = "";
    } catch (failure) {
      if (current !== generation) return;
      data.value = emptyValue();
      error.value = failure.message || "Не удалось загрузить данные";
    }
  };
}
