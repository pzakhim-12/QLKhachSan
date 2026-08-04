import hashlib
import hmac
import urllib.parse

class vnpay:
    # Khởi tạo nơi lưu
    def __init__(self):
        self.requestData = {}
        self.responseData = {}

    # Tạo đường link để chuyển hướng sang trang thanh toán VNPay
    def get_payment_url(self, vnpay_payment_url, secret_key):
        """Hàm sinh ra URL chuyển hướng đến trang thanh toán của VNPay"""
        inputData = sorted(self.requestData.items())
        queryString = ''
        hasData = ''
        seq = 0
        for key, val in inputData:
            if str(val) != '' and str(val) != 'None':
                if seq == 1:
                    queryString = queryString + "&" + key + '=' + urllib.parse.quote_plus(str(val))
                else:
                    seq = 1
                    queryString = key + '=' + urllib.parse.quote_plus(str(val))

        # Tạo mã băm bảo mật
        hashValue = self.__hmacsha512(secret_key, queryString)
        return vnpay_payment_url + "?" + queryString + '&vnp_SecureHash=' + hashValue

    # Kiểm tra xem dữ liệu thanh toán VNPay trả về có bị giả mạo không
    def validate_response(self, secret_key):
        """Hàm kiểm tra tính hợp lệ của dữ liệu VNPay trả về (chống giả mạo)"""
        vnp_SecureHash = self.responseData.get('vnp_SecureHash')
        
        # Loại bỏ các trường hash ra khỏi dữ liệu cần băm
        if 'vnp_SecureHash' in self.responseData:
            self.responseData.pop('vnp_SecureHash')
        if 'vnp_SecureHashType' in self.responseData:
            self.responseData.pop('vnp_SecureHashType')

        inputData = sorted(self.responseData.items())
        hasData = ''
        seq = 0
        for key, val in inputData:
            if str(key).startswith('vnp_'):
                if str(val) != '' and str(val) != 'None':
                    if seq == 1:
                        hasData = hasData + "&" + str(key) + '=' + urllib.parse.quote_plus(str(val))
                    else:
                        seq = 1
                        hasData = str(key) + '=' + urllib.parse.quote_plus(str(val))

        hashValue = self.__hmacsha512(secret_key, hasData)
        return vnp_SecureHash == hashValue

    # Hàm phụ trợ dùng để mã hóa dữ liệu bảo mật (chuẩn SHA512)
    def __hmacsha512(self, key, data):
        """Thuật toán mã hóa HMAC SHA512 theo chuẩn VNPay"""
        byteKey = key.encode('utf-8')
        byteData = data.encode('utf-8')
        return hmac.new(byteKey, byteData, hashlib.sha512).hexdigest()