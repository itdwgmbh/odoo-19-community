document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('label[for="master_pwd"]').forEach((label) => {
        label.textContent = "Admin JWT";
    });
    document.querySelectorAll('input[name="master_pwd"]').forEach((input) => {
        input.autocomplete = "off";
    });
    document.querySelectorAll('[data-bs-target=".o_database_master"], .o_database_master').forEach((element) => {
        element.remove();
    });
});
