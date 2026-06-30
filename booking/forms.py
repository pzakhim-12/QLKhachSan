from django import forms
from .models import Booking

class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        # Chỉ hiển thị 2 trường cho khách chọn, User và Room hệ thống sẽ tự lo
        fields = ['check_in', 'check_out'] 
        
        # Thêm class của Bootstrap và biến nó thành bộ lịch chọn ngày
        widgets = {
            'check_in': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'check_out': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }