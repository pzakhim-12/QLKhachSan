document.addEventListener("DOMContentLoaded", function () {
    document.body.addEventListener('change', function (e) {
        if (e.target && e.target.type === 'file') {
            const file = e.target.files[0];
            if (file && file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = function (event) {
                    // tìm thẻ chứa ảnh xung quanh nút upload để thay đổi
                    let container = e.target.parentElement;
                    while (container && !container.querySelector('img')) {
                        container = container.parentElement;
                        if (container.tagName === 'BODY') break;
                    }
                    if (container) {
                        const img = container.querySelector('img');
                        if (img) {
                            img.src = event.target.result;
                        }
                    }
                }
                reader.readAsDataURL(file);
            }
        }
    });
});